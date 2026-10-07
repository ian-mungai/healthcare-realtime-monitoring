{{ config(enabled=var('cohort_reference_enabled', false)) }}

{#- Patients that share a reused waveform record must share a split. -#}
select groups.split_group
from {{ ref('ml_training_dataset') }} as training
inner join {{ source('cohort_reference', 'patient_split_groups') }} as groups
    on training.patient_key = {{ stable_key('groups.patient_id') }}
group by groups.split_group
having count(distinct training.data_split) > 1
