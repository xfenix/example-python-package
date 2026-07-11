# PLAN.md — загрузчик CSV/XLSX в реляционную таблицу

Итог grill-сессии. Всё, что не попало в scope, вырезано осознанно (см. «Не-цели»).

## 1. Цель

CLI-утилита поверх библиотечного ядра: берёт `.csv` / `.xlsx`, инферит типы
колонок, проверяет атомарность значений и грузит данные в **одну плоскую**
таблицу реляционной БД (Postgres / MariaDB / SQLite). Потоково, любой размер.

Один вызов:

```
tableload load <file> --db <url> [--table NAME] [--if-exists fail|append|replace] [--no-header]
```

## 2. Не-цели (осознанно вырезано)

- **Нормализация до 3NF, поиск функциональных зависимостей, кандидатные ключи** —
  выброшено. Доказать FD по сэмплу нельзя, а нормализация требует реляций.
- **Реляции / внешние ключи / разбиение на несколько таблиц** — запрещены
  архитектурно. Инструмент физически не умеет создавать больше одной таблицы.
- **Эвристики «массив по разделителю»** (`a;b;c`) — нет. Массив = только JSON-литерал.
- **Свои адаптеры под каждую БД** — нет. Всё через SQLAlchemy Core.
- **Dataframe-библиотеки** (pandas/polars) — нет, стриминг через stdlib + openpyxl.
- **Upsert / dedup / первичные ключи** — нет ключей → нет upsert. Только insert.

## 3. Архитектура

Ядро — библиотека, CLI — тонкий враппер. Единственный внешний шов (`Protocol`) —
чтение строк, чтобы CSV и XLSX были взаимозаменяемы и легко добавлялся новый формат.

```
tableload/
  __init__.py      # публичный API: load_file(...)
  readers.py       # Protocol RowReader + CsvReader + XlsxReader + выбор по расширению
  inference.py     # лестница типов, инференс, маппинг в типы SQLAlchemy
  validation.py    # проверка атомарности (JSON array/object) + сбор Violation
  schema.py        # построение sa.Table, санитизация имён, рефлексия для append
  loader.py        # оркестратор: два прохода, транзакция, батчи, if-exists
  config.py        # pydantic-settings: db url / env
  errors.py        # типы исключений
  cli.py           # argparse, точка входа
tests/
  test_inference.py
  test_validation.py
  test_loader.py    # интеграционные, sqlite in-memory
  conftest.py
```

Поток: `cli` → `config` → `readers.build_reader(path)` →
`loader.load(reader, engine, options)`, где `loader` вызывает `inference`
(проход 1) и запись (проход 2).

## 4. Типы данных

### 4.1 Лестница инференса (проход 1)

Для каждой колонки держим множество ещё-возможных типов; каждое непустое
значение вычёркивает типы, под которые не подошло. Итог — самый узкий выживший
по приоритету. Пустая ячейка = NULL, в инференсе игнорируется. Колонка целиком
из пустых → `TEXT`, `nullable=True`.

Приоритет (узкий → широкий):

| Тип       | Правило (значение подходит, если…)                          | SQLAlchemy тип |
|-----------|-------------------------------------------------------------|----------------|
| bool      | `strip().lower() in {"true", "false"}` (НЕ 0/1 — не путать с int) | `sa.Boolean`   |
| int       | `^-?\d+$` и влезает в 64 бита                                | `sa.BigInteger`|
| decimal   | парсится `decimal.Decimal`, есть дробь / не влезло в int     | `sa.Numeric(p, s)` |
| date      | `datetime.date.fromisoformat`                               | `sa.Date`      |
| datetime  | `datetime.datetime.fromisoformat`                           | `sa.DateTime`  |
| text      | всё остальное (fallback)                                     | `sa.Text`      |

- `Numeric(p, s)`: точность/масштаб считаем по максимуму разрядов в колонке
  (нужно для MariaDB, у Postgres NUMERIC безразмерный). Считаем в том же проходе 1.
- Регулярки анкорные и простые — ReDoS не грозит.
- **XLSX**: openpyxl уже отдаёт нативные `int/float/datetime/bool` → лестница
  применяется только к строковым ячейкам; типизированные берём как есть.
- `nullable` = была ли в колонке хоть одна пустая ячейка.

### 4.2 Доменные dataclass'ы (frozen, slots, @final)

```python
@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class ColumnSpec:
    column_name: str
    sql_type: sa.types.TypeEngine[typing.Any]
    is_nullable: bool

@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class AtomicityViolation:
    row_number: int          # 1-based, как в файле
    column_name: str
    offending_value: str

@typing.final
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoadReport:
    table_name: str
    inserted_rows: int
    inferred_columns: tuple[ColumnSpec, ...]
```

## 5. Шов чтения (Protocol)

Два прохода ⇒ ридер должен переоткрываться (держит путь, отдаёт свежий итератор).

```python
class RowReader(typing.Protocol):
    @property
    def header(self) -> tuple[str, ...]: ...
    def iterate_rows(self) -> collections.abc.Iterator[tuple[object, ...]]: ...
```

- `CsvReader`: stdlib `csv`, потоково.
- `XlsxReader`: `openpyxl.load_workbook(read_only=True)`, потоково по строкам.
- `build_reader(path)`: выбор по расширению; `--no-header` → синтетические `col_1..N`.
- Санитизация имён: пустой заголовок → `col_N`; дубли → суффикс `_2`, `_3`;
  всё прочее (юникод, регистр, пробелы) не трогаем — SQLAlchemy квотит идентификаторы.

## 6. Валидатор (единственное правило данных)

Ячейка нарушает атомарность, если `strip()` парсится `json.loads` в `list` или
`dict`. Всё остальное — атомарный скаляр. Проверка идёт в проходе 1 вместе с
инференсом (один проход по данным на обе задачи).

Политика: собрать **все** нарушения (до кап-лимита, напр. 1000) → не вставлять
ничего → вернуть отчёт → `exit != 0`. Файл либо чистый целиком, либо отклонён.

«Нет реляций» — не проверка строк, а инвариант: всегда одна таблица, никаких FK.

## 7. Запись в БД (мульти-БД через SQLAlchemy Core)

Один кодовый путь. Отличия Postgres/Maria/SQLite берёт на себя диалект: компиляция
DDL, маппинг типов, батч-insert. **Новая БД в будущем = новый URL + диалект, кода не пишем.**

Проход 2:
1. Если таблицы нет → `CREATE TABLE` из `ColumnSpec` (DDL компилит SQLAlchemy).
2. `--if-exists`:
   - `fail` (по умолчанию) — таблица есть → ошибка, ничего не трогаем.
   - `append` — рефлексим существующую таблицу, проверяем что все колонки файла
     есть в таблице (по именам); несовпадение → ошибка с отчётом.
   - `replace` — `DROP` + `CREATE`.
3. Стрим-вставка батчами (по умолчанию 10 000 строк) в **одной транзакции** —
   любая ошибка на проходе 2 → полный rollback.
4. Транзиентные ошибки коннекта — ретрай через `stamina` (ограниченный,
   с джиттером). Саму транзакцию не ретраим — только установку соединения.

## 8. Конфиг

`pydantic-settings`: `--db <url>` флагом, иначе из env (`TABLELOAD_DB_URL`).
`--table` по умолчанию = stem имени файла. Батч-размер — константа с флагом-оверрайдом.

## 9. Обработка ошибок

- Свои исключения в `errors.py`: `TableAlreadyExistsError`, `SchemaMismatchError`,
  `AtomicityError` (несёт список нарушений), `UnsupportedFormatError`.
- Ловим конкретные типы, не `except Exception`. LBYL: наличие таблицы/колонок
  проверяем заранее, а не через перехват.
- CLI мапит исключения в человекочитаемый вывод + ненулевой код возврата.

## 10. Стандарты (pylines)

- ruff `select = ALL`, mypy `--strict`, uv, длина строки 120.
- 100% аннотаций; классы `@final`; dataclass `kw_only/slots/frozen`; `typing.Final`
  на переменные; `Protocol` для шва чтения; композиция, без глубоких иерархий.
- Имена — глаголами, ≥8 символов (`infer_column_types`, `build_reader`,
  `detect_violations`, `reflect_existing_table`).
- Встроенные модули импортим целиком (`import json`, `import csv`, `import decimal`).

## 11. Тесты

- Интеграционные важнее юнитов: гоняем реальную загрузку против **SQLite
  in-memory** (тот же код-путь, что и для Postgres/Maria).
- `faker` для данных, `@pytest.mark.parametrize` на форматы/типы, `pytest-xdist -n auto`.
- Ключевые кейсы: лестница типов на границах (bool vs 0/1, big int → decimal,
  ISO-даты), NULL-колонки, JSON-массив/объект → отклонение с полным отчётом,
  `fail/append/replace`, несовпадение колонок при append, CSV без заголовка.
- Минимум один прогоняемый self-check (`demo()` на assert'ах) в `inference` и
  `validation` — падает, если лестница/детектор массива сломались.

## 12. Зависимости

`sqlalchemy`, `openpyxl`, `pydantic-settings`, `stamina`.
Dev: `ruff`, `mypy`, `pytest`, `pytest-xdist`, `faker`, `community-of-python-flake8-plugin`.
Драйверы БД по месту: `psycopg`, `mysqlclient`/`PyMySQL` (sqlite — из stdlib).

## 13. Этапы реализации

1. **Каркас**: `uv init`, `pyproject.toml` (ruff/mypy/flake8 из гайдлайнов), пакет, CLI-заглушка.
2. **Ридеры**: `RowReader` Protocol + `CsvReader` + `XlsxReader` + `build_reader`. Тесты чтения.
3. **Инференс**: лестница типов + Numeric precision + маппинг в SQLAlchemy. Юнит-тесты границ.
4. **Валидатор**: детектор JSON array/object + сбор `AtomicityViolation`. Тесты.
5. **Схема**: санитизация имён, `build_table`, рефлексия для append.
6. **Loader**: два прохода, транзакция, батчи, `--if-exists`, `stamina`-ретрай. Интеграционные тесты на sqlite.
7. **CLI + config**: argparse, pydantic-settings, маппинг ошибок → exit codes.
8. **Прогон** на реальных CSV/XLSX против локального Postgres и MariaDB (docker), проверка отчётов.
