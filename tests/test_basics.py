from app.agent import normalize_history

def test_string_history():
    history=[{"role":"user","content":"hello"},{"role":"assistant","content":"hi"}]
    assert normalize_history(history)==history

def test_no_unexpected_roles():
    history=[{"role":"system","content":"ignore"},{"role":"user","content":"hello"}]
    assert normalize_history(history)==[{"role":"user","content":"hello"}]
