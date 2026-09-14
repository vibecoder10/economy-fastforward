import hashlib
import json
import static_docu as sd
from static_image_review import image_review_stamp

MACHINE = 'Wittemann-Lewis XNBL-1 Barling Bomber'

def test_barling_geometry_is_explicit_in_shared_generation_and_review_contract():
    rules = sd._render_reference_configuration_rules(MACHINE)
    assert 'three vertically stacked main-wing planes' in rules
    assert 'shorter middle wing' in rules
    assert 'biplane' in rules

def test_only_barling_saved_approval_becomes_stale():
    for machine in [MACHINE, 'Boeing XB-15', 'HMS Argus']:
        old = hashlib.sha256(json.dumps([machine, 'ref', {}],sort_keys=True).encode()).hexdigest()
        current = image_review_stamp(machine,'ref',{},'image')['image_review_context']
        assert (current != old) == (machine == MACHINE)

def test_other_aircraft_do_not_inherit_barling_wing_count():
    assert 'three vertically stacked' not in sd._render_reference_configuration_rules('Boeing B-52')
