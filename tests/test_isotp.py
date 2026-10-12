import pytest
from mokka_ecu_lab.protocols import parse_obd
from mokka_ecu_lab.protocols.isotp import parse_reply
from mokka_ecu_lab.transport.simulator import can_reply


@pytest.mark.parametrize('ecu',['7E8','18DAF110'])
@pytest.mark.parametrize('length',[7,8,9,10,13,119,120,128,4093])
def test_exact_payload_roundtrip_sequence_wrap_and_padding(ecu,length):
    payload=bytes(i%256 for i in range(length))
    raw=(can_reply(ecu,0x7F,payload)+'\r>').encode()
    response,=parse_obd(raw,0x7F)
    assert response.header==ecu and response.data==payload


@pytest.mark.parametrize('raw',[
    b'7E8 10 0B 41 78 0F 0D 48 10\r>',
    b'7E8 10 0B 41 78 0F 0D 48 10\r7E8 22 68 11 30 0E 10 00 00\r>',
    b'7E8 21 68 11 30 0E 10 00 00\r>',
    b'7E8 10 0B 41 78 0F 0D 48 10\r7E8 21 68 11\r>',
    b'7E8 10 07 41 78 0F 0D 48 10\r>',
    b'7E8 10 00 41 78 0F 0D 48 10\r>',
    b'7E8 10 0B 41 78 0F 0D 48 10\r7E8 10 0B 41 78 0F 0D 48 10\r>',
    b'7E8 9 10 0B 41 78 0F 0D 48 10\r>',
    b'7E8 8 03 41 78 00\r>',
    b'7E8 10 0B 41 78 0F 0D 48 10\r7E8 21 ZZ 11 30 0E 10 00 00\r>',
])
def test_truncation_bad_sequence_length_dlc_and_hex_never_decode(raw):
    result=parse_reply(raw,0x78)
    assert result.errors and not result.responses
    with pytest.raises(ValueError): parse_obd(raw,0x78)


def test_interleaved_ecus_never_mix_payloads_and_isolate_failure():
    good=can_reply('7E8',0x78,bytes.fromhex('01 0D 48 00 00 00 00 00 00')).split('\r')
    bad=can_reply('7E9',0x78,bytes.fromhex('01 10 68 00 00 00 00 00 00')).split('\r')
    raw=('\r'.join([good[0],bad[0],good[1],bad[1].replace('7E9 21','7E9 22')])+'\r>').encode()
    result=parse_reply(raw,0x78)
    assert [(r.header,r.data[:3]) for r in result.responses]==[('7E8',bytes.fromhex('01 0D 48'))]
    assert {e['ecu'] for e in result.errors}=={'7E9'}


def test_completed_payload_is_discarded_after_duplicate_cf():
    lines=can_reply('7E8',0x85,b'\x04'+bytes(9)).split('\r')
    result=parse_reply(('\r'.join(lines+[lines[-1]])+'\r>').encode(),0x85)
    assert not result.responses and result.errors


def test_headerless_elm_segmented_output_has_no_invented_ecu():
    reply,=parse_obd(b'0178\r00B\r0: 41 78 01 0D 48 00\r1: 00 00 00 00 00\r>',0x78,'0178')
    assert reply.header is None and reply.data==bytes.fromhex('01 0D 48 00 00 00 00 00 00')


@pytest.mark.parametrize('raw',[
    b'00B\r0:41 78 01 0D 48 00\r2:00 00 00 00 00\r>',
    b'00B\r0:41 78 01 0D 48 00\r1:00 00\r>',
    b'00B\r00B\r0:41 78 01 0D 48 00\r1:00 00 00 00 00\r>',
    b'00B\r0:41 78 01 0D 48 00\r7E8 21 00 00 00 00 00 00 00\r>',
    b'00B\r0:41 78 01 0D 48 00\r0:41 78 01 0D 48 00\r>',
])
def test_segmented_output_rejects_ambiguity_and_missing_bytes(raw):
    assert parse_reply(raw,0x78).errors
    assert not parse_reply(raw,0x78).responses


def test_compact_multiframe_and_optional_dlc():
    original=can_reply('18DAF110',0x8B,bytes.fromhex('73 03 80 01 2C 01 5E'))
    for text in [original.replace(' ',''), original.replace('18DAF110 ','18DAF110 8 ')]:
        assert parse_obd((text+'\r>').encode(),0x8B)[0].data==bytes.fromhex('73 03 80 01 2C 01 5E')


def test_documented_elm_flow_control_display_does_not_become_payload():
    text=can_reply('7E8',0x8B,bytes.fromhex('01 00 00 00 00 00 00'))
    assert parse_obd(('7E0 30 00 00 00 00 00 00 00\r'+text+'\r>').encode(),0x8B)[0].header=='7E8'
def test_duplicate_single_frame_is_not_a_second_measurement():
    result=parse_reply(b'7E8 03 41 05 60\r7E8 03 41 05 60\r>',0x05)
    assert not result.responses and result.errors
