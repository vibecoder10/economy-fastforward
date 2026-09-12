import asyncio
from unittest.mock import AsyncMock

import channel_format as cf


def test_only_explicit_channel_contract_is_applied(monkeypatch):
    fetch=AsyncMock(return_value={'channel_identity':{'machine_script_contract':'factual_100_v1'}})
    write=AsyncMock(return_value='UPDATE 1')
    monkeypatch.setattr(cf,'fetch_one',fetch)
    monkeypatch.setattr(cf,'execute',write)
    assert asyncio.run(cf.apply_machine_script_contract('tenant','video')) is True
    args=write.await_args.args
    assert args[1:]==('factual_100_v1','video','tenant')
    assert "render_mode='static_docu'" in args[0]
    assert "AND NOT" in args[0]
    fetch.return_value={'channel_identity':{}}
    assert asyncio.run(cf.apply_machine_script_contract('tenant','video')) is False
    assert write.await_count==1
