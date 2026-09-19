# -*- coding: utf-8 -*-
"""Reviewed product-category and material-type applicability aliases."""


PRODUCT_CATEGORY_FAMILIES = (
    frozenset({"食品", "保健食品", "进口保健食品", "营养补充", "滋补保健"}),
    frozenset({"美妆", "普通化妆品", "护肤", "彩妆", "唇部护理"}),
)

MATERIAL_TYPE_FAMILIES = (
    frozenset({"短视频", "视频", "短视频脚本", "短视频脚本中的文字内容"}),
    frozenset({"图文", "图文文案"}),
    frozenset({"详情页", "详情页文字"}),
    frozenset({"Banner", "Banner文字"}),
)


def expand_product_categories(values):
    variants = set(values or [])
    for value in set(variants):
        if value.endswith("产品") and len(value) > 2:
            variants.add(value[:-2])
        elif value.endswith(("品", "类")) and len(value) >= 4:
            variants.add(value[:-1])
        for family in PRODUCT_CATEGORY_FAMILIES:
            if value in family:
                variants.update(family)
    return variants


def expand_material_types(values):
    variants = set(values or [])
    for value in set(variants):
        for family in MATERIAL_TYPE_FAMILIES:
            if value in family:
                variants.update(family)
    return variants


def material_type_scope_matches(allowed_values, actual_value):
    allowed = expand_material_types({
        str(value).strip() for value in (allowed_values or []) if str(value).strip()
    })
    actual = expand_material_types({str(actual_value or "").strip()})
    actual.discard("")
    return not allowed or not actual or bool(allowed & actual)
