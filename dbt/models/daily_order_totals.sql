select workspace || ':' || order_date::text as workspace_day,
       workspace, order_date, count(*) as order_count, sum(amount) as order_total
from {{ source('operations', 'orders') }}
group by workspace, order_date
