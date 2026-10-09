import pytest
from helpers.data_source_test_helper import DataSourceTestHelper
from helpers.test_fixtures import test_datasource
from helpers.test_functions import get_diagnostic_value
from helpers.test_table import TestTableSpecification
from soda_core.contracts.contract_verification import ContractVerificationResult

# Two shards whose unique names share the prefix SODATEST_wildcard_shard_, so the wildcard
# table SODATEST_wildcard_shard_* spans both of them.
shard_a_specification = (
    TestTableSpecification.builder()
    .table_purpose("wildcard_shard_a")
    .column_varchar("id")
    .column_integer("size")
    .rows(rows=[("1", 10), ("2", None)])
    .build()
)

shard_b_specification = (
    TestTableSpecification.builder()
    .table_purpose("wildcard_shard_b")
    .column_varchar("id")
    .column_integer("size")
    .rows(rows=[("3", 30)])
    .build()
)


# A separate wildcard family, SODATEST_wildcard_schema_*, so the extra column of the newest
# table does not leak into the shard tests above.
older_schema_specification = (
    TestTableSpecification.builder()
    .table_purpose("wildcard_schema_older")
    .column_varchar("id")
    .rows(rows=[("1",)])
    .build()
)

newest_schema_specification = (
    TestTableSpecification.builder()
    .table_purpose("wildcard_schema_newest")
    .column_varchar("id")
    .column_integer("extra")
    .rows(rows=[("2", 20)])
    .build()
)

pytestmark = pytest.mark.skipif(test_datasource != "bigquery", reason="BigQuery-specific: wildcard tables")


@pytest.fixture
def wildcard_dqn(data_source_test_helper: DataSourceTestHelper) -> str:
    data_source_test_helper.ensure_test_table(shard_a_specification)
    data_source_test_helper.ensure_test_table(shard_b_specification)
    return "/".join(
        [data_source_test_helper.data_source_impl.name]
        + data_source_test_helper.dataset_prefix
        + ["SODATEST_wildcard_shard_*"]
    )


def test_wildcard_table_spans_all_shards(data_source_test_helper: DataSourceTestHelper, wildcard_dqn: str):
    contract_verification_result: ContractVerificationResult = data_source_test_helper.assert_contract_pass(
        test_table=None,
        contract_yaml_str=f"""
            dataset: {wildcard_dqn}
            columns:
              - name: id
              - name: size
                checks:
                  - missing:
                      threshold:
                        must_be: 1
            checks:
              - schema:
              - row_count:
                  threshold:
                    must_be: 3
        """,
    )
    missing_check_result = contract_verification_result.check_results[0]
    assert get_diagnostic_value(check_result=missing_check_result, diagnostic_name="missing_count") == 1


def test_wildcard_table_filters_on_table_suffix(data_source_test_helper: DataSourceTestHelper, wildcard_dqn: str):
    data_source_test_helper.assert_contract_pass(
        test_table=None,
        contract_yaml_str=f"""
            dataset: {wildcard_dqn}
            filter: _TABLE_SUFFIX LIKE 'a%'
            columns:
              - name: id
              - name: size
            checks:
              - row_count:
                  threshold:
                    must_be: 2
        """,
    )


def test_wildcard_schema_comes_from_newest_matching_table(data_source_test_helper: DataSourceTestHelper):
    data_source_test_helper.ensure_test_table(older_schema_specification)
    # Recreated every run: test tables are otherwise reused, so creation order would not be guaranteed.
    data_source_test_helper.ensure_test_table(newest_schema_specification, force_recreate=True)
    wildcard_dqn: str = "/".join(
        [data_source_test_helper.data_source_impl.name]
        + data_source_test_helper.dataset_prefix
        + ["SODATEST_wildcard_schema_*"]
    )

    # `extra` only exists in the newest table, so the schema check passes only when the
    # wildcard schema is read from it rather than from the older table.
    data_source_test_helper.assert_contract_pass(
        test_table=None,
        contract_yaml_str=f"""
            dataset: {wildcard_dqn}
            columns:
              - name: id
              - name: extra
            checks:
              - schema:
        """,
    )
