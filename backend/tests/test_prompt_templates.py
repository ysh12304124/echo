from app.providers.local.prompt_templates import render_prompt_template


def test_render_prompt_template_substitutes_variables():
    rendered = render_prompt_template(
        "query_multimodal_user.md",
        question="图片是什么颜色？",
        evidence_context="[visual] 红色测试图片",
    )

    assert "问题: 图片是什么颜色？" in rendered
    assert "[visual] 红色测试图片" in rendered
