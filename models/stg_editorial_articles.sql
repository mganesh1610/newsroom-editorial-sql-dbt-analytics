-- dbt / BigQuery-compatible staging model for raw digital editorial articles.
-- Normalizes channel taxonomy flags, derives publication day index (chronological),
-- and surfaces upstream scraper / instrumentation quality defects before downstream marts.

WITH source_articles AS (
    SELECT
        TRIM(url) AS article_url,
        CAST(timedelta AS INTEGER) AS days_before_snapshot,
        (731 - CAST(timedelta AS INTEGER)) AS pub_day_seq,
        CAST(n_tokens_title AS INTEGER) AS title_word_count,
        CAST(n_tokens_content AS INTEGER) AS body_word_count,
        CAST(num_hrefs AS INTEGER) AS outbound_link_count,
        CAST(num_self_hrefs AS INTEGER) AS internal_link_count,
        CAST(num_imgs AS INTEGER) AS image_count,
        CAST(num_videos AS INTEGER) AS video_count,
        CAST(num_keywords AS INTEGER) AS tag_keyword_count,
        CAST(kw_avg_avg AS REAL) AS avg_keyword_share_velocity,
        CAST(self_reference_avg_shares AS REAL) AS internal_ref_avg_shares,
        CAST(global_subjectivity AS REAL) AS global_subjectivity,
        CAST(global_sentiment_polarity AS REAL) AS global_sentiment_polarity,
        CAST(title_subjectivity AS REAL) AS title_subjectivity,
        CAST(title_sentiment_polarity AS REAL) AS title_sentiment_polarity,
        CAST(data_channel_is_lifestyle AS INTEGER) AS is_lifestyle,
        CAST(data_channel_is_entertainment AS INTEGER) AS is_entertainment,
        CAST(data_channel_is_bus AS INTEGER) AS is_business,
        CAST(data_channel_is_socmed AS INTEGER) AS is_social_media,
        CAST(data_channel_is_tech AS INTEGER) AS is_tech,
        CAST(data_channel_is_world AS INTEGER) AS is_world,
        CAST(weekday_is_monday AS INTEGER) AS is_monday,
        CAST(weekday_is_tuesday AS INTEGER) AS is_tuesday,
        CAST(weekday_is_wednesday AS INTEGER) AS is_wednesday,
        CAST(weekday_is_thursday AS INTEGER) AS is_thursday,
        CAST(weekday_is_friday AS INTEGER) AS is_friday,
        CAST(weekday_is_saturday AS INTEGER) AS is_saturday,
        CAST(weekday_is_sunday AS INTEGER) AS is_sunday,
        CAST(is_weekend AS INTEGER) AS is_weekend,
        CAST(shares AS INTEGER) AS shares
    FROM raw_editorial_articles
),

taxonomy_normalized AS (
    SELECT
        *,
        CASE
            WHEN is_business = 1 THEN 'Business'
            WHEN is_world = 1 THEN 'World'
            WHEN is_tech = 1 THEN 'Tech'
            WHEN is_entertainment = 1 THEN 'Entertainment'
            WHEN is_lifestyle = 1 THEN 'Lifestyle'
            WHEN is_social_media = 1 THEN 'Social Media'
            ELSE 'Unassigned'
        END AS editorial_desk,
        (is_lifestyle + is_entertainment + is_business + is_social_media + is_tech + is_world) AS desk_flag_sum,
        CASE
            WHEN is_monday = 1 THEN 'Monday'
            WHEN is_tuesday = 1 THEN 'Tuesday'
            WHEN is_wednesday = 1 THEN 'Wednesday'
            WHEN is_thursday = 1 THEN 'Thursday'
            WHEN is_friday = 1 THEN 'Friday'
            WHEN is_saturday = 1 THEN 'Saturday'
            WHEN is_sunday = 1 THEN 'Sunday'
            ELSE 'Unknown'
        END AS publish_weekday,
        (is_monday + is_tuesday + is_wednesday + is_thursday + is_friday + is_saturday + is_sunday) AS weekday_flag_sum
    FROM source_articles
)

SELECT
    article_url,
    days_before_snapshot,
    pub_day_seq,
    editorial_desk,
    publish_weekday,
    is_weekend,
    title_word_count,
    body_word_count,
    outbound_link_count,
    internal_link_count,
    image_count,
    video_count,
    tag_keyword_count,
    avg_keyword_share_velocity,
    internal_ref_avg_shares,
    global_subjectivity,
    global_sentiment_polarity,
    title_subjectivity,
    title_sentiment_polarity,
    shares,
    LN(1.0 + shares) AS log1p_shares,
    CASE WHEN body_word_count = 0 THEN 1 ELSE 0 END AS flag_zero_body_parser_defect,
    CASE WHEN editorial_desk = 'Unassigned' THEN 1 ELSE 0 END AS flag_missing_desk_taxonomy,
    CASE WHEN desk_flag_sum > 1 THEN 1 ELSE 0 END AS flag_multi_desk_collision,
    CASE WHEN weekday_flag_sum <> 1 THEN 1 ELSE 0 END AS flag_invalid_weekday_flag
FROM taxonomy_normalized;
