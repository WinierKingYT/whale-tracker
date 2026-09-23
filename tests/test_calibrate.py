from whale_tracker import calibrate


def test_run_one_returns_a_scorecard_with_seed_tagged():
    scorecard = calibrate.run_one(1, cycles=20, min_usd=1_000_000.0)
    assert scorecard["seed"] == 1
    assert "closed_position_count" in scorecard


def test_run_one_uses_its_own_isolated_temp_db_not_shared_state():
    """Two runs with the same seed but called independently must produce
    identical results -- proves each run starts from a fresh, isolated
    database rather than accumulating into shared state."""
    first = calibrate.run_one(7, cycles=30, min_usd=1_000_000.0)
    second = calibrate.run_one(7, cycles=30, min_usd=1_000_000.0)
    assert first["closed_position_count"] == second["closed_position_count"]
    assert first["win_rate"] == second["win_rate"]


def test_run_batch_produces_one_scorecard_per_seed():
    scorecards = calibrate.run_batch(3, cycles=20, min_usd=1_000_000.0, base_seed=100)
    assert len(scorecards) == 3
    assert [s["seed"] for s in scorecards] == [100, 101, 102]


def test_summarize_excludes_runs_with_no_closed_positions_from_means():
    scorecards = [
        {"closed_position_count": 0, "seed": 1},
        {
            "closed_position_count": 4, "seed": 2, "win_rate": 0.5,
            "strategy_return_pct": 0.02, "btc_hold_return_pct": 0.01,
            "avg_win_pct": 0.03, "avg_loss_pct": -0.02, "max_drawdown_pct": 0.01,
            "beats_btc_hold": True,
        },
    ]
    summary = calibrate.summarize(scorecards)
    assert summary["num_runs"] == 2
    assert summary["runs_with_closed_positions"] == 1
    assert summary["runs_with_no_data"] == 1
    assert summary["mean_win_rate"] == 0.5
    assert summary["pct_runs_beating_btc_hold"] == 1.0
    assert summary["pct_runs_net_positive"] == 1.0


def test_summarize_handles_all_runs_empty():
    summary = calibrate.summarize([{"closed_position_count": 0, "seed": 1}])
    assert summary["runs_with_closed_positions"] == 0
    assert summary["mean_win_rate"] is None
    assert summary["pct_runs_beating_btc_hold"] is None


def test_render_summary_handles_zero_data_runs():
    summary = calibrate.summarize([{"closed_position_count": 0, "seed": 1}])
    report = calibrate.render_summary(summary)
    assert "Hiçbir çalıştırmada pozisyon kapanmadı" in report


def test_render_summary_flags_asymmetric_win_loss_pattern():
    summary = {
        "num_runs": 2, "runs_with_closed_positions": 2, "runs_with_no_data": 0,
        "mean_closed_positions": 10.0, "mean_win_rate": 0.7,
        "mean_avg_win_pct": 0.004, "mean_avg_loss_pct": -0.04,
        "mean_strategy_return_pct": -0.01, "mean_btc_hold_return_pct": -0.03,
        "mean_max_drawdown_pct": 0.02, "pct_runs_beating_btc_hold": 1.0,
        "pct_runs_net_positive": 0.0,
    }
    report = calibrate.render_summary(summary)
    assert "[BULGU]" in report


def test_render_summary_does_not_flag_symmetric_win_loss():
    summary = {
        "num_runs": 2, "runs_with_closed_positions": 2, "runs_with_no_data": 0,
        "mean_closed_positions": 10.0, "mean_win_rate": 0.5,
        "mean_avg_win_pct": 0.03, "mean_avg_loss_pct": -0.03,
        "mean_strategy_return_pct": 0.01, "mean_btc_hold_return_pct": 0.005,
        "mean_max_drawdown_pct": 0.02, "pct_runs_beating_btc_hold": 0.5,
        "pct_runs_net_positive": 0.5,
    }
    report = calibrate.render_summary(summary)
    assert "[BULGU]" not in report
