from unittest.mock import MagicMock

from soda_bigquery.common.data_sources.bigquery_data_source import (
    BigQueryDataSourceImpl,
    BigQueryDataSourceNamespace,
    BigQuerySqlDialect,
)
from soda_core.common.data_source_results import QueryResult
from soda_core.common.sql_ast import COUNT, FROM, SELECT, STAR

PREFIXES = ["my-proj", "analytics"]


def test_wildcard_table_renders_as_one_backticked_path():
    # BigQuery documents the wildcard form as a single backticked path.
    dialect = BigQuerySqlDialect()
    sql = dialect.build_select_sql([SELECT(COUNT(STAR())), FROM("events_*", table_prefix=PREFIXES)])
    assert sql == "SELECT COUNT(*)\nFROM `my-proj.analytics.events_*`;"


def test_wildcard_table_qualified_name_is_one_backticked_path():
    dialect = BigQuerySqlDialect()
    assert dialect.qualify_dataset_name(PREFIXES, "events_*") == "`my-proj.analytics.events_*`"


def test_non_wildcard_table_keeps_per_part_quoting():
    dialect = BigQuerySqlDialect()
    assert dialect.qualify_dataset_name(PREFIXES, "events") == "`my-proj`.`analytics`.`events`"
    sql = dialect.build_select_sql([SELECT(COUNT(STAR())), FROM("events", table_prefix=PREFIXES)])
    assert "FROM `my-proj`.`analytics`.`events`;" in sql


def test_wildcard_only_as_last_character():
    dialect = BigQuerySqlDialect()
    assert dialect.is_wildcard_table_name("events_*")
    assert not dialect.is_wildcard_table_name("events_*_old")
    assert not dialect.is_wildcard_table_name("events")
    assert not dialect.is_wildcard_table_name(None)


def test_newest_wildcard_match_query_escapes_like_wildcards_in_prefix():
    dialect = BigQuerySqlDialect()
    sql = dialect.build_newest_wildcard_match_query_str(
        table_namespace=BigQueryDataSourceNamespace(project_id="my-proj", dataset="analytics"),
        wildcard_table_name="events_*",
    )
    assert "FROM `my-proj`.`analytics`.`INFORMATION_SCHEMA`.`TABLES`" in sql
    assert "`TABLE_TYPE` = '''BASE TABLE'''" in sql
    # The literal decodes to events\_% : `_` matches literally, `%` takes the place of `*`.
    assert "`TABLE_NAME` like '''events\\\\_%'''" in sql
    assert "ORDER BY `CREATION_TIME` DESC" in sql
    assert sql.endswith("LIMIT 1;")


def _make_impl(query_results: list[QueryResult]) -> BigQueryDataSourceImpl:
    impl = BigQueryDataSourceImpl.__new__(BigQueryDataSourceImpl)
    impl.sql_dialect = BigQuerySqlDialect()
    impl.execute_query = MagicMock(side_effect=query_results)
    return impl


def _columns_result() -> QueryResult:
    return QueryResult(
        rows=[("id", "STRING"), ("amount", "INT64")],
        columns=(("COLUMN_NAME",), ("DATA_TYPE",)),
    )


def test_wildcard_columns_metadata_comes_from_newest_matching_table():
    impl = _make_impl([QueryResult(rows=[("events_20240102",)], columns=(("TABLE_NAME",),)), _columns_result()])

    columns = impl.get_columns_metadata(dataset_prefixes=PREFIXES, dataset_name="events_*")

    assert [column.column_name for column in columns] == ["id", "amount"]
    newest_match_sql, columns_sql = [call.args[0] for call in impl.execute_query.call_args_list]
    assert "`INFORMATION_SCHEMA`.`TABLES`" in newest_match_sql
    assert "`TABLE_NAME` = '''events_20240102'''" in columns_sql


def test_wildcard_without_matching_table_has_no_columns():
    impl = _make_impl([QueryResult(rows=[], columns=(("TABLE_NAME",),))])

    assert impl.get_columns_metadata(dataset_prefixes=PREFIXES, dataset_name="events_*") == []
    assert impl.execute_query.call_count == 1


def test_non_wildcard_columns_metadata_queries_the_table_directly():
    impl = _make_impl([_columns_result()])

    impl.get_columns_metadata(dataset_prefixes=PREFIXES, dataset_name="events")

    (columns_sql,) = [call.args[0] for call in impl.execute_query.call_args_list]
    assert "`TABLE_NAME` = '''events'''" in columns_sql
