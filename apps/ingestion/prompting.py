"""Load the shared policy and one mode prompt from the repository prompts directory."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

MODE_FILES = {
    "JOB_PARSER": "job_parser.txt",
    "CV_OPTIMIZER": "cv_optimizer.txt",
    "MOCK_INTERVIEW": "mock_interview.txt",
    "CANDIDATE_REPORT": "candidate_report.txt",
    "RECRUITER_EVALUATION": "recruiter_evaluation.txt",
}


def load_shared_policy() -> str:
    return (PROMPTS_DIR / "shared_policy.txt").read_text(encoding="utf-8").strip()


def load_mode_prompt(mode: str) -> str:
    try:
        filename = MODE_FILES[mode]
    except KeyError as exc:
        known = ", ".join(MODE_FILES)
        raise KeyError(f"Unknown mode {mode}. Known modes: {known}.") from exc
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def system_instruction(mode: str) -> str:
    """Shared policy, then exactly one mode prompt."""
    return f"{load_shared_policy()}\n\n{load_mode_prompt(mode)}\n"
