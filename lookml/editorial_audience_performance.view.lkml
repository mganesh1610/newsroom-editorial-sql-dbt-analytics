view: editorial_audience_performance {
  sql_table_name: `analytics_prod.fct_editorial_desk_daily` ;;
  label: "Editorial & Audience Daily Desk Performance"

  dimension: desk_day_pk {
    primary_key: yes
    hidden: yes
    type: string
    sql: CONCAT(CAST(${pub_day_seq} AS STRING), '_', ${editorial_desk}) ;;
  }

  dimension: pub_day_seq {
    type: number
    label: "Publication Day Sequence"
    description: "Chronological day index (0 to 723) normalized from source timedelta."
    sql: ${TABLE}.pub_day_seq ;;
  }

  dimension: editorial_desk {
    type: string
    label: "Editorial Desk"
    description: "Normalized topic channel (Business, World, Tech, Entertainment, Lifestyle, Social Media, Unassigned)."
    sql: ${TABLE}.editorial_desk ;;
  }

  dimension: publish_weekday {
    type: string
    label: "Publish Weekday"
    sql: ${TABLE}.publish_weekday ;;
  }

  dimension: is_weekend {
    type: yesno
    label: "Weekend Publication?"
    sql: ${TABLE}.is_weekend = 1 ;;
  }

  dimension: is_traffic_spike_2sigma {
    type: yesno
    label: "2-Sigma Traffic Spike Day"
    description: "True when daily desk mean log1p_shares exceeds trailing 14-day mean by >= 2.0 SD."
    sql: ${TABLE}.is_traffic_spike_2sigma = 1 ;;
  }

  measure: published_articles {
    type: sum
    label: "Published Articles"
    sql: ${TABLE}.published_articles ;;
    value_format_name: decimal_0
  }

  measure: total_shares {
    type: sum
    label: "Total Audience Shares"
    sql: ${TABLE}.total_shares ;;
    value_format_name: decimal_0
  }

  measure: avg_shares_per_article {
    type: number
    label: "Mean Shares per Article"
    sql: SAFE_DIVIDE(${total_shares}, ${published_articles}) ;;
    value_format_name: decimal_1
  }

  measure: high_velocity_articles {
    type: sum
    label: "High-Velocity Stories (>=3,400 Shares)"
    sql: ${TABLE}.high_velocity_articles ;;
    value_format_name: decimal_0
  }

  measure: high_velocity_rate {
    type: number
    label: "High-Velocity Rate"
    sql: SAFE_DIVIDE(${high_velocity_articles}, ${published_articles}) ;;
    value_format_name: percent_2
  }

  measure: zero_body_defect_count {
    type: sum
    label: "Zero-Body Parser Defects"
    sql: ${TABLE}.zero_body_defect_count ;;
    value_format_name: decimal_0
  }

  measure: missing_taxonomy_count {
    type: sum
    label: "Missing Desk Taxonomy Rows"
    sql: ${TABLE}.missing_taxonomy_count ;;
    value_format_name: decimal_0
  }
}
