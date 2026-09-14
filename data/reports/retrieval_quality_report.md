# Retrieval Quality Report

> 小规模人工回归集，只用于防止已知问题复发，不代表全量生产准确率。

| requested_mode | effective_mode | semantic_status | passed | total | pass_rate |
| --- | --- | --- | --- | ---: | ---: |
| lexical | lexical | disabled | 9 | 9 | 100.00% |
| hybrid | hybrid | ready | 9 | 9 | 100.00% |

## Cases

| mode | evaluation_id | expected | actual | passed | method | similarity |
| --- | --- | --- | --- | --- | --- | ---: |
| lexical | positive_food_disease_claim | samr_2025_typical_ads_02 | ['samr_2025_typical_ads_02'] | YES | fielded_bm25_v2 | - |
| lexical | positive_absolute_and_state_authority | samr_2025_typical_ads_05 | ['samr_2025_typical_ads_05'] | YES | fielded_bm25_v2 | - |
| lexical | positive_real_estate | samr_2025_typical_ads_07 | ['samr_2025_typical_ads_07'] | YES | fielded_bm25_v2 | - |
| lexical | positive_prescription_drug_science_content | samr_2025_typical_ads_10 | ['samr_2025_typical_ads_10'] | YES | fielded_bm25_v2 | - |
| lexical | positive_unreviewed_medical_device_ad | samr_2025_typical_ads_08 | ['samr_2025_typical_ads_08'] | YES | fielded_bm25_v2 | - |
| lexical | negative_benign_nutrition_copy | [] | [] | YES | fielded_bm25_v2 | - |
| lexical | negative_unsupported_sales_claim | [] | [] | YES | fielded_bm25_v2 | - |
| lexical | negative_benign_cosmetic_copy | [] | [] | YES | fielded_bm25_v2 | - |
| lexical | semantic_only_prescription_drug_paraphrase | [] | [] | YES | fielded_bm25_v2 | - |
| hybrid | positive_food_disease_claim | samr_2025_typical_ads_02 | ['samr_2025_typical_ads_02', 'samr_2025_typical_ads_04', 'samr_2025_typical_ads_08'] | YES | hybrid_rrf_v1 | - |
| hybrid | positive_absolute_and_state_authority | samr_2025_typical_ads_05 | ['samr_2025_typical_ads_05'] | YES | hybrid_rrf_v1 | - |
| hybrid | positive_real_estate | samr_2025_typical_ads_07 | ['samr_2025_typical_ads_07'] | YES | hybrid_rrf_v1 | 0.725465 |
| hybrid | positive_prescription_drug_science_content | samr_2025_typical_ads_10 | ['samr_2025_typical_ads_10'] | YES | hybrid_rrf_v1 | 0.794932 |
| hybrid | positive_unreviewed_medical_device_ad | samr_2025_typical_ads_08 | ['samr_2025_typical_ads_08'] | YES | hybrid_rrf_v1 | 0.740604 |
| hybrid | negative_benign_nutrition_copy | [] | [] | YES | hybrid_rrf_v1 | - |
| hybrid | negative_unsupported_sales_claim | [] | [] | YES | hybrid_rrf_v1 | - |
| hybrid | negative_benign_cosmetic_copy | [] | [] | YES | hybrid_rrf_v1 | - |
| hybrid | semantic_only_prescription_drug_paraphrase | samr_2025_typical_ads_10 | ['samr_2025_typical_ads_10'] | YES | hybrid_rrf_v1 | 0.742925 |
