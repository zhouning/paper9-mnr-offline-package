from paper9_mnr.audit import build_audit_summary, evaluate_hard_constraints


def _config():
    return {
        "algorithm": {"name": "paper9v2"},
        "planning": {
            "constraints": {
                "cultivated_area_floor_delta_ha": 0,
            },
        },
    }


def test_evaluate_hard_constraints_passes_required_gates():
    mpc_summary = {
        "results": [
            {
                "cultivated_area_change_ha": 0.25,
                "slope_change_pct": -0.1,
                "cont_change": 0.02,
                "baimu_count_change": 1,
                "baimu_area_change_ha": -10.0,
            }
        ]
    }

    status = evaluate_hard_constraints(_config(), mpc_summary)

    assert status["hard_constraint_passed"] is True
    assert status["failure_reasons"] == []
    assert status["baimu_is_hard_constraint"] is False


def test_evaluate_hard_constraints_reports_all_required_gate_failures():
    mpc_summary = {
        "results": [
            {
                "cultivated_area_change_ha": -1.5,
                "slope_change_pct": 0.01,
                "cont_change": 0.0,
                "baimu_count_change": 3,
                "baimu_area_change_ha": 12.0,
            }
        ]
    }

    status = evaluate_hard_constraints(_config(), mpc_summary)

    assert status["hard_constraint_passed"] is False
    assert status["failure_reasons"] == [
        "episode 0 cultivated_area_change_ha=-1.500000 < required 0.000000",
        "episode 0 slope_change_pct=0.010000 does not satisfy slope_change_pct < 0",
        "episode 0 cont_change=0.000000 does not satisfy cont_change > 0",
    ]


def test_evaluate_hard_constraints_fails_empty_results():
    status = evaluate_hard_constraints(_config(), {"results": []})

    assert status["hard_constraint_passed"] is False
    assert status["failure_reasons"] == ["mpc_summary.results is empty"]


def test_build_audit_summary_fails_when_mpc_summary_is_missing(tmp_path):
    config = {
        "data": {
            "prepared_dir": tmp_path / "prepared",
        },
        "training": {
            "out_subdir": "tool3",
        },
        "outputs": {
            "plan_dir": tmp_path / "plan",
            "optimized_vector": tmp_path / "plan" / "DLTB_optimized.gpkg",
        },
        "planning": {
            "constraints": {
                "cultivated_area_floor_delta_ha": 0,
            },
        },
    }

    summary = build_audit_summary(config)

    assert summary["constraint_status"]["hard_constraint_passed"] is False
    assert summary["constraint_status"]["failure_reasons"] == ["mpc_summary.json is missing"]


def test_build_audit_summary_marks_dltb_only_regulatory_constraints_not_evaluated(tmp_path):
    config = {
        "input_profile": {
            "mode": "dltb_dem_only",
            "evidence_tier": "exploratory_data_limited",
            "unavailable_authority_data": {
                "pdt": "not_provided_not_evaluated",
                "eco_redline": "not_provided_not_evaluated",
                "permanent_basic_farmland": "not_provided_not_evaluated",
            },
            "decision_use": "exploratory_technical_validation_only",
        },
        "data": {"prepared_dir": tmp_path / "prepared"},
        "training": {"out_subdir": "tool3"},
        "outputs": {
            "plan_dir": tmp_path / "plan",
            "optimized_vector": tmp_path / "plan" / "DLTB_optimized.shp",
        },
        "planning": {"constraints": {"cultivated_area_floor_delta_ha": 0}},
    }

    summary = build_audit_summary(config)

    profile = summary["input_profile_status"]
    assert profile["regulatory_constraints_evaluated"] is False
    assert profile["regulatory_compliance_claim_allowed"] is False
    assert profile["decision_use"] == "exploratory_technical_validation_only"
