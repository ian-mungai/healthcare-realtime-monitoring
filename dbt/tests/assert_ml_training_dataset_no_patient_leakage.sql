select patient_key
from {{ ref('ml_training_dataset') }}
group by patient_key
having count(distinct data_split) > 1
