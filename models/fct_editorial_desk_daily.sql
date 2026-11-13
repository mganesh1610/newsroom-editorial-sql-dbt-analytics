-- Governed self-serve BI mart: daily editorial desk performance, engagement tiers,
-- and source instrumentation health indicators for Looker / Tableau / Mode reporting.

WITH desk_enriched AS (
    SELECT
        s.pub_day_seq,
        s.editorial_desk,
        s.publish_weekday,
        s.is_weekend,
        s.shares,
        s.log1p_shares,
        s.body_word_count,
        s.image_count,
        s.video_count,
        s.internal_link_count,
        s.flag_zero_body_parser_defect,
        s.flag_missing_desk_taxonomy,
        CASE WHEN s.shares >= 3400 THEN 1 ELSE 0 END AS is_high_velocity_story,
        CASE WHEN s.shares >= 1400 THEN 1 ELSE 0 END AS is_above_median_story
    FROM stg_editorial_articles AS s
)

SELECT
    d.pub_day_seq,
    d.editorial_desk,
    MAX(d.publish_weekday) AS publish_weekday,
    MAX(d.is_weekend) AS is_weekend,
    COUNT(*) AS published_articles,
    SUM(d.shares) AS total_shares,
    ROUND(AVG(d.shares), 2) AS avg_shares_per_article,
    ROUND(AVG(d.log1p_shares), 4) AS avg_log1p_shares,
    SUM(d.is_high_velocity_story) AS high_velocity_articles,
    SUM(d.is_above_median_story) AS above_median_articles,
    ROUND(100.0 * SUM(d.is_high_velocity_story) / COUNT(*), 2) AS high_velocity_rate_pct,
    ROUND(AVG(CASE WHEN d.flag_zero_body_parser_defect = 0 THEN d.body_word_count END), 1) AS clean_avg_word_count,
    ROUND(AVG(d.image_count), 2) AS avg_images,
    ROUND(AVG(d.video_count), 2) AS avg_videos,
    ROUND(AVG(d.internal_link_count), 2) AS avg_internal_links,
    SUM(d.flag_zero_body_parser_defect) AS zero_body_defect_count,
    SUM(d.flag_missing_desk_taxonomy) AS missing_taxonomy_count,
    COALESCE(sp.is_traffic_spike_2sigma, 0) AS is_traffic_spike_2sigma,
    COALESCE(sp.rolling_14d_zscore, 0.0) AS rolling_14d_zscore
FROM desk_enriched AS d
LEFT JOIN int_editorial_spike_events AS sp
    ON d.pub_day_seq = sp.pub_day_seq
   AND d.editorial_desk = sp.editorial_desk
GROUP BY d.pub_day_seq, d.editorial_desk;
