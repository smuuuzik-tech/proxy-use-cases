import json

from proxy_b2b_client.cli import EXIT_CONFIGURATION, main


def test_argument_errors_are_emitted_as_json(capsys):
    exit_code = main(["https://api.example.test", "--method", "INVALID"])
    captured = capsys.readouterr()

    assert exit_code == EXIT_CONFIGURATION
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "configuration_error"


def test_non_finite_json_body_is_a_configuration_error(
    capsys, monkeypatch, tmp_path
):
    body = tmp_path / "body.json"
    body.write_text('{"value": NaN}', encoding="utf-8")
    monkeypatch.setenv("B2B_PROXY_URL", "http://proxy.example.test:8080")

    exit_code = main(
        [
            "https://api.example.test",
            "--method",
            "POST",
            "--json-body-file",
            str(body),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_CONFIGURATION
    assert payload["error"]["code"] == "configuration_error"
