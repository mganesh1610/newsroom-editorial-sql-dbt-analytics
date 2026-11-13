-- Intermediate SQL model identifying high-impact publishing days and performance shifts
-- using 14-day trailing rolling z-scores (strictly causal window: 14 PRECEDING to 1 PRECEDING).

WITH daily_desk_agg AS (
    SELECT
        pub_day_seq,
        editorial_desk,
        COUNT(*) AS article_count,
        SUM(shares) AS total_shares,
        AVG(shares) AS avg_shares,
        AVG(log1p_shares) AS avg_log1p_shares,
        SUM(flag_zero_body_parser_defect) AS zero_body_defects
    FROM stg_editorial_articles
    GROUP BY pub_day_seq, editorial_desk
),

trailing_window AS (
    SELECT
        pub_day_seq,
        editorial_desk,
        article_count,
        total_shares,
        avg_shares,
        avg_log1p_shares,
        zero_body_defects,
        COUNT(*) OVER (
            PARTITION BY editorial_desk
            ORDER BY pub_day_seq
            ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING
        ) AS trailing_obs_days,
        AVG(avg_log1p_shares) OVER (
            PARTITION BY editorial_desk
            ORDER BY pub_day_seq
            ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING
        ) AS trailing_14d_mean_log_shares,
        AVG(avg_log1p_shares * avg_log1p_shares) OVER (
            PARTITION BY editorial_desk
            ORDER BY pub_day_seq
            ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING
        ) AS trailing_14d_mean_sq_log_shares
    FROM daily_desk_agg
),

zscore_scored AS (
    SELECT
        pub_day_seq,
        editorial_desk,
        article_count,
        total_shares,
        ROUND(avg_shares, 2) AS avg_shares,
        ROUND(avg_log1p_shares, 4) AS avg_log1p_shares,
        trailing_obs_days,
        ROUND(trailing_14d_mean_log_shares, 4) AS trailing_14d_mean_log_shares,
        ROUND(
            SQRT(
                MAX(
                    0.0,
                    trailing_14d_mean_sq_log_shares
                    - (trailing_14d_mean_log_shares * trailing_14d_mean_log_shares)
                )
            ),
            4
        ) AS trailing_14d_sd_log_shares,
        zero_body_defects
    FROM trailing_window
)

SELECT
    pub_day_seq,
    editorial_desk,
    article_count,
    total_shares,
    avg_shares,
    avg_log1p_shares,
    trailing_obs_days,
    trailing_14d_mean_log_shares,
    trailing_14d_sd_log_shares,
    CASE
        WHEN trailing_obs_days >= 7 AND trailing_14d_sd_log_shares > 0.05
        THEN ROUND((avg_log1p_shares - trailing_14d_mean_log_shares) / trailing_14d_sd_log_shares, 4)
        ELSE 0.0
    END AS rolling_14d_zscore,
    CASE
        WHEN trailing_obs_days >= 7
             AND trailing_14d_sd_log_shares > 0.05
             AND ((avg_log1p_shares - trailing_14d_mean_log_shares) / trailing_14d_sd_log_shares) >= 2.0
        THEN 1
        ELSE 0
    END AS is_traffic_spike_2sigma,
    zero_body_defects
FROM zscore_scored;
