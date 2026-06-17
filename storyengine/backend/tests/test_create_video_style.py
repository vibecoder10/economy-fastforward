from models import CreateVideoRequest

def test_new_style_fields_default_safe():
    r = CreateVideoRequest(title="t")
    assert r.image_style_override is None
    assert r.lock_in_identity is False
    assert r.visual_style_label is None

def test_new_style_fields_accept_values():
    r = CreateVideoRequest(title="t", image_style_override="soft 3D Pixar CG",
                           lock_in_identity=True, visual_style_label="Pixar 3D")
    assert r.image_style_override == "soft 3D Pixar CG"
    assert r.lock_in_identity is True
    assert r.visual_style_label == "Pixar 3D"
