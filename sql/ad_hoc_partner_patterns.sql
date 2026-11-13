-- Reusable SQL analytics patterns for answering recurring editorial, audience,
-- and product partner questions cleanly and consistently.

-- Pattern 1: Desk Scorecard (Volume, Share Reach, High-Velocity Rate, Defect Rate)
SELECT
    editorial_desk,
    COUNT(*) AS articles_published,
    SUM(shares) AS cumulative_shares,
    ROUND(AVG(shares), 1) AS mean_shares,
    SUM(CASE WHEN shares >= 3400 THEN 1 ELSE 0 END) AS top_decile_proxy_stories,
    ROUND(100.0 * SUM(CASE WHEN shares >= 3400 THEN 1 ELSE 0 END) / COUNT(*), 2) AS viral_rate_pct,
    SUM(flag_zero_body_parser_defect) AS parser_zero_body_rows
FROM stg_editorial_articles
GROUP BY editorial_desk
ORDER BY cumulative_shares DESC;

-- Pattern 2: Weekday vs. Weekend Audience Consumption Shift by Desk
SELECT
    editorial_desk,
    CASE WHEN is_weekend = 1 THEN 'Weekend' ELSE 'Weekday' END AS day_cohort,
    COUNT(*) AS articles,
    ROUND(AVG(shares), 1) AS mean_shares,
    ROUND(AVG(log1p_shares), 4) AS mean_log1p_shares
FROM stg_editorial_articles
GROUP BY editorial_desk, is_weekend
ORDER BY editorial_desk, is_weekend;

-- Pattern 3: Multimedia Enrichment Lift (Videos & Internal Links vs. Baseline)
SELECT
    CASE
        WHEN video_count > 0 AND internal_link_count >= 3 THEN 'Video + Deep Internal Linking'
        WHEN video_count > 0 THEN 'Video Present Only'
        WHEN internal_link_count >= 3 THEN 'Deep Internal Linking Only'
        ELSE 'Standard Text Baseline'
    END AS content_format_bucket,
    COUNT(*) AS articles,
    ROUND(AVG(shares), 1) AS mean_shares,
    ROUND(100.0 * SUM(CASE WHEN shares >= 3400 THEN 1 ELSE 0 END) / COUNT(*), 2) AS high_velocity_pct
FROM stg_editorial_articles
WHERE flag_zero_body_parser_defect = 0
GROUP BY content_format_bucket
ORDER BY high_velocity_pct DESC;

-- Pattern 4: Source Instrumentation & Taxonomy Defect Audit Summary
SELECT
    SUM(flag_zero_body_parser_defect) AS zero_body_parser_rows,
    SUM(flag_missing_desk_taxonomy) AS unassigned_desk_rows,
    SUM(flag_multi_desk_collision) AS multi_desk_collision_rows,
    SUM(flag_invalid_weekday_flag) AS invalid_weekday_rows,
    COUNT(*) AS total_staged_articles
FROM stg_editorial_articles;
