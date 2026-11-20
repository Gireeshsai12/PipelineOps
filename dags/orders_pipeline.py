import os
from datetime import timedelta

import pendulum
from airflow.decorators import dag, task

from ops import pipeline


def recover_failure(context):
    requested = (context["dag_run"].conf or {}).get("pipeline_run_id")
    resolved = context["ti"].xcom_pull(task_ids="resolve")
    run_id = resolved or requested or str(pipeline.scheduled_id(context["run_id"]))
    run = pipeline.lookup(run_id)
    if run:
        pipeline.finish(run, "failed", "Airflow marked this execution failed")


@dag(dag_id="orders_pipeline", start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
     schedule=os.getenv("PIPELINE_SCHEDULE", "0 4 * * *"), catchup=False,
     max_active_runs=1, on_failure_callback=recover_failure,
     default_args={"execution_timeout": timedelta(minutes=4)})
def orders_pipeline():
    @task
    def resolve(**context):
        return pipeline.resolve(context["run_id"], (context["dag_run"].conf or {}).get("pipeline_run_id"))

    @task
    def ingestion(pipeline_run_id):
        pipeline.execute(pipeline_run_id, "ingestion", pipeline.ingest)

    @task
    def validation(pipeline_run_id):
        pipeline.execute(pipeline_run_id, "validation", pipeline.validate)

    @task
    def loading(pipeline_run_id):
        pipeline.execute(pipeline_run_id, "loading", pipeline.load)

    @task
    def dbt_transformation(pipeline_run_id):
        run = pipeline.execute(pipeline_run_id, "dbt", pipeline.transform)
        pipeline.finish(run, "succeeded", "Pipeline completed")

    run_id = resolve()
    ingestion(run_id) >> validation(run_id) >> loading(run_id) >> dbt_transformation(run_id)


orders_pipeline()
