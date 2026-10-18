import pytest

from cashguard.config import Settings
from cashguard.pipeline import analyze
from cashguard.schemas import Scan, Verification
from cashguard.departure import DepartureScan
from cashguard.workflow import WorkflowContext, context_hint, observe_workflow
from test_service import FakeModel, video


def context(end=2):
    return WorkflowContext(cashier_spatial_role='Synthetic operator at desk', phases=[dict(
        kind='employee_cash_work', start_sec=0, end_sec=end, confidence=.9,
        observation='Synthetic employee-only counting')])


def test_phase_outside_recording_is_failure_not_clean_negative(video):
    class Model:
        def ask(self, *args): return context(1000)
    with pytest.raises(ValueError, match='outside'):
        observe_workflow(video, 3, Settings(), Model(), 100)


def test_context_does_not_override_pixel_verification(video):
    class Model(FakeModel):
        def ask(self, prompt, frames, schema, deadline):
            if schema is WorkflowContext:return context()
            assert 'UNTRUSTED context hypothesis' in prompt
            assert 'cannot prove a missing action' in prompt
            if schema in {Scan, Verification, DepartureScan}:
                assert 'employee_cash_work' in prompt
            return super().ask(prompt,frames,schema,deadline)
    result=analyze(video,Settings(workflow_context=True,identity_checks=False),model=Model(confirmed=False))
    assert result['verdict']=='no_violation'
    assert result['analysis']['workflow_context']['phases']==['employee_cash_work']


def test_nonoverlapping_phase_not_forwarded_as_current_observation():
    hint=context_hint(context(),3,4)
    assert '"overlapping_phases": []' in hint
    assert 'Synthetic employee-only counting' not in hint
    assert context_hint(None,0,3)==''
