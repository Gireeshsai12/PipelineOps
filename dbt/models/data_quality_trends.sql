{{ config(materialized="view") }}

with violations as (
  select run_id, count(distinct row_num) as rejected_orders
  from {{ source('operations', 'validation_failures') }}
  group by run_id
)
select r.workspace || ':' || r.start_date::text as workspace_day, r.workspace,
       r.start_date as source_date, count(*) as runs,
       count(*) filter (where r.status = 'failed') as failed_runs,
       sum(coalesce(v.rejected_orders,0)) as rejected_orders
from {{ source('operations', 'runs') }} r
left join violations v on v.run_id = r.id
where r.started_at is not null
group by r.workspace, r.start_date
