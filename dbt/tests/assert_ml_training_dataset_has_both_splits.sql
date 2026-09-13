with available_splits as (
    select data_split
    from {{ ref('ml_training_dataset') }}
    group by data_split
)

select 'missing_train_or_test_split' as failure
where (select count(*) from available_splits) <> 2
