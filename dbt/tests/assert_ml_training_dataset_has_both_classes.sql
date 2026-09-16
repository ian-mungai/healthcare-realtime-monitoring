with split_class_counts as (
    select
        data_split,
        count(distinct deterioration_proxy_label) as class_count
    from {{ ref('ml_training_dataset') }}
    group by data_split
)

select *
from split_class_counts
where class_count <> 2
