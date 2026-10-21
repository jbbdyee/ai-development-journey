from pathlib import Path

from tcrew.cli import main
from tcrew.core import load_config, run


CONFIG = Path(__file__).resolve().parents[1] / "crew.yaml"


class FakeLLM:
    def __init__(self):
        self.calls = []

    def complete(self, *, model, role, instruction, prompt):
        self.calls.append((model, role, instruction, prompt))
        if role == "reviewer":
            return "PASS\n검토 완료"
        return f"{role}의 결과"


def test_roles_run_in_yaml_order_and_receive_prior_outputs():
    fake = FakeLLM()
    results = run("VPN 공지", load_config(CONFIG), fake)
    assert [call[1] for call in fake.calls] == ["writer", "reviewer", "editor"]
    assert all(call[0] == "gpt-4.1-mini" for call in fake.calls)
    assert "VPN 공지" in fake.calls[0][3]
    assert "writer의 결과" in fake.calls[1][3]
    assert "writer의 결과" in fake.calls[2][3]
    assert "PASS\n검토 완료" in fake.calls[2][3]
    assert [result.output for result in results] == ["writer의 결과", "PASS\n검토 완료", "editor의 결과"]


def test_plain_cli_uses_fake_llm_and_prints_each_role(capsys, tmp_path):
    fake = FakeLLM()
    assert main(["VPN 공지", "--plain", "--config", str(CONFIG)], llm=fake, runs_dir=tmp_path) == 0
    output = capsys.readouterr().out
    assert output.index("=== writer ===") < output.index("=== reviewer ===") < output.index("=== editor ===")
    assert "writer의 결과" in output
    assert "PASS\n검토 완료" in output
    assert "editor의 결과" in output
