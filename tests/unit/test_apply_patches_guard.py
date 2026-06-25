from backend.pipeline.passes.editor.editor import apply_patches


def test_non_dict_patch_element_skipped():
    # The guard exists for runtime input the type system forbids, so the bad
    # element is deliberately the wrong type here.
    patches = [{"search": "foo", "replace": "bar"}, "junk"]
    draft, errors = apply_patches("draft foo", patches)  # type: ignore[arg-type]
    assert draft == "draft bar"
    assert errors == []
