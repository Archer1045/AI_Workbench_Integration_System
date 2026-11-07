"""Lace, sheer, transparent, private, and open-structure clothing presets."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _parts(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]


def build_presets(
    factory: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add(
        preset_id: str,
        category: str,
        label: str,
        translation: str,
        tags: str,
        *,
        part: str = "全身",
        intensity: str = "强化",
        materials: str = "网纱|合成纤维",
        accessories: str = "",
    ) -> None:
        items.append(
            factory(
                preset_id,
                category,
                label,
                translation,
                _parts(tags),
                gender="女",
                part=part,
                nsfw=True,
                intensity=intensity,
                materials=_parts(materials),
                accessories=_parts(accessories),
                draw_prompt=f"wearing {tags}",
                has_image=False,
            )
        )

    # Transparent private base layer.
    add("sheer_tulle_frame_bralette_set", "情趣内衣", "透明薄纱框式胸衣套装", "薄纱胸衣、独立框架、细肩带与配套内裤", "sheer tulle bralette|frame bra|thin straps|matching panties|see-through lingerie", part="内衣", accessories="独立框架|细肩带")
    add("transparent_lace_contour_bodysuit", "情趣内衣", "透明蕾丝轮廓连体衣", "透明蕾丝勾勒身体轮廓，贴身连体结构", "transparent lace bodysuit|contour fit|see-through lace|fitted silhouette", part="内衣")
    add("lace_illusion_garter_teddy", "情趣内衣", "蕾丝幻影吊袜连体衣", "不透明蕾丝边缘与透明主体组合，带吊袜带", "lace illusion teddy|garter straps|sheer panels|opaque lace trim|lingerie", part="内衣", accessories="吊袜带")
    add("tulle_ribbon_open_back_set", "情趣内衣", "薄纱缎带露背套装", "薄纱主体、缎带连接和开放背部", "tulle ribbon lingerie|open back|satin ribbons|sheer panels|lingerie set", part="内衣", materials="网纱|丝", accessories="缎带|露背结构")
    add("sheer_lace_layered_slip", "情趣内衣", "透明蕾丝层叠吊带裙", "多层薄纱与蕾丝吊带裙，轻透垂坠", "sheer lace slip|layered tulle|lace trim|thin straps|see-through dress", part="内衣", accessories="层叠薄纱|蕾丝边")
    add("transparent_lace_high_waist_set", "情趣内衣", "透明蕾丝高腰套装", "高腰结构与透明蕾丝拼接", "transparent lace lingerie|high-waist briefs|sheer panels|lace trim|lingerie set", part="内衣")
    add("tulle_lace_cutout_bralette_set", "情趣内衣", "薄纱蕾丝镂空胸衣套装", "镂空胸衣、薄纱侧片与细带结构", "tulle lace bralette|cutout bra|sheer side panels|strappy lingerie|matching panties", part="内衣", accessories="镂空裁片|细带")
    add("sheer_lace_corset_brief_set", "情趣内衣", "透明蕾丝束腰内裤套装", "透明蕾丝束腰与低腰内裤组合", "sheer lace corset|briefs|transparent panels|lace trim|lingerie set", part="内衣", materials="网纱|丝")

    # Private open structures.
    add("lace_frame_open_front_teddy", "情趣内衣", "蕾丝框架前开连体衣", "前开结构与蕾丝框架连接，保持完整连体轮廓", "lace frame teddy|open front|minimal lace connectors|body-focused lingerie", part="内衣", accessories="前开结构|蕾丝框架")
    add("tulle_side_window_bodysuit", "情趣内衣", "薄纱侧视窗连体衣", "两侧透明视窗与不透明主体拼接", "tulle side-window bodysuit|sheer side panels|opaque center panel|fitted lingerie", part="内衣")
    add("sheer_lace_split_cup_babydoll", "情趣内衣", "透明蕾丝分罩杯睡裙", "分罩杯、蕾丝罩面与透明下摆", "sheer lace babydoll|split cups|lace cups|see-through hem|thin straps", part="内衣", accessories="分罩杯|透明下摆")
    add("transparent_lace_open_bust_corset", "情趣内衣", "透明蕾丝开胸束身衣", "开胸束身轮廓与透明蕾丝层", "transparent lace corset|open bust|sheer corset|lace panels|lingerie", part="内衣", materials="网纱|丝|金属", accessories="开胸结构|透明蕾丝")
    add("lace_minimal_bridge_teddy", "情趣内衣", "蕾丝极简桥接连体衣", "蕾丝只保留关键连接结构，强调身体轮廓", "minimal lace teddy|bridge connectors|body-focused lingerie|open construction", part="内衣", intensity="极限", accessories="极简连接桥")
    add("tulle_open_hip_garter_bodysuit", "情趣内衣", "薄纱开胯吊袜连体衣", "薄纱主体、开放胯部与吊袜连接", "tulle open-hip bodysuit|open hip cutouts|garter straps|sheer lingerie", part="内衣", accessories="开胯结构|吊袜带")
    add("sheer_lace_waist_cutout_set", "情趣内衣", "透明蕾丝腰部镂空套装", "腰部视窗、透明蕾丝与独立上下装", "sheer lace waist set|waist cutout|transparent lace|two-piece lingerie", part="内衣", accessories="腰部视窗")
    add("transparent_lace_back_window_set", "情趣内衣", "透明蕾丝背部视窗套装", "背部大面积透明视窗和蕾丝边框", "transparent lace back set|back window|sheer back|lace frame|lingerie set", part="内衣", accessories="背部视窗|蕾丝边框")

    # Sleepwear and peignoir.
    add("sheer_lace_layer_peignoir_set", "情趣内衣", "透明蕾丝层叠晨袍套装", "长晨袍、多层薄纱与蕾丝边缘", "sheer lace peignoir|layered tulle robe|lace trim|long robe|lingerie set", part="内衣", materials="网纱|丝", accessories="多层薄纱|蕾丝边缘")
    add("tulle_train_sheer_nightgown", "内衣/睡衣", "薄纱拖尾透明睡裙", "透明睡裙与独立薄纱拖尾", "sheer nightgown|tulle train|see-through sleepwear|thin straps", part="内衣", accessories="薄纱拖尾")
    add("lace_hooded_sheer_robe", "内衣/睡衣", "蕾丝连帽透明晨袍", "连帽轮廓和透明蕾丝主体", "lace hooded robe|sheer robe|open front robe|lace trim", part="内衣", accessories="连帽结构|蕾丝边")
    add("open_front_tulle_slip_dress", "内衣/睡衣", "前开薄纱吊带裙", "前开结构、薄纱裙层和细吊带", "open-front tulle slip|sheer slip dress|thin straps|layered tulle", part="内衣", accessories="前开结构")
    add("transparent_lace_sleep_shorts_set", "内衣/睡衣", "透明蕾丝睡衣短裤套装", "轻量上衣与透明蕾丝短裤", "sheer lace sleep set|lace shorts|transparent sleepwear|camisole set", part="内衣")
    add("layered_tulle_lace_lounge_dress", "内衣/睡衣", "薄纱蕾丝层叠居家裙", "居家轮廓、薄纱外层和蕾丝边缘", "tulle lounge dress|lace trim|layered sheer skirt|soft homewear", materials="网纱|棉|丝")

    # Swimwear and wet looks.
    add("sheer_lace_open_cut_monokini", "泳装/运动", "透明蕾丝开放裁片泳装", "透明蕾丝覆盖与开放裁片组合", "sheer lace monokini|open cutouts|transparent lace|swimsuit", part="泳装", intensity="极限", accessories="开放裁片")
    add("tulle_overlay_wet_look_swimsuit", "泳装/运动", "薄纱层叠湿感泳装", "泳装主体、薄纱外层和湿亮质感", "tulle overlay swimsuit|wet-look swimwear|sheer overlay|glossy swimsuit", part="泳装")
    add("transparent_lace_beach_bodysuit", "泳装/运动", "透明蕾丝海滩连体衣", "透明蕾丝与海滩连体轮廓", "transparent lace beach bodysuit|sheer beachwear|fitted beach bodysuit", part="泳装")
    add("sheer_tulle_poolside_cover_set", "泳装/运动", "透明薄纱泳池罩衫套装", "泳装与长薄纱罩衫组合", "sheer tulle pool coverup|swimsuit set|long sheer coverup|poolside outfit", part="泳装")

    # Body-jewelry integration.
    add("transparent_lace_chest_frame_set", "配饰", "透明蕾丝胸饰框架套装", "蕾丝框架连接胸部区域和既有饰品", "transparent lace chest frame|body jewelry frame|lace connectors|completed static jewelry", part="配饰", intensity="极限", materials="金属|网纱|丝", accessories="胸饰框架|蕾丝连接")
    add("sheer_tulle_waist_chain_set", "配饰", "薄纱腰链套装", "透明腰部结构与装饰链", "sheer tulle waist chain|waist jewelry|lace waist panel|completed static jewelry", part="配饰", materials="金属|网纱", accessories="腰链|薄纱腰饰")
    add("lace_garter_intimate_frame_set", "配饰", "蕾丝吊袜私密饰框套装", "吊袜、蕾丝与私密饰框组合", "lace garter frame|intimate jewelry frame|lace connectors|completed static jewelry", part="配饰", intensity="极限", materials="金属|网纱|丝", accessories="吊袜|私密饰框")
    add("tulle_multi_point_jewelry_bodysuit", "配饰", "薄纱多点饰品连体衣", "薄纱主体连接多个饰品点", "tulle multi-point jewelry|body jewelry connectors|sheer jewelry display|completed static jewelry", part="配饰", intensity="极限", materials="金属|网纱", accessories="多点连接饰")
    add("lace_nipple_jewelry_illusion_set", "配饰", "蕾丝乳饰幻影套装", "蕾丝与既有乳饰形成视觉融合", "lace nipple jewelry illusion|existing nipple jewelry|lace accents|completed static jewelry", part="配饰", intensity="极限", materials="金属|网纱|丝", accessories="蕾丝乳饰框")
    add("sheer_lace_thigh_jewelry_set", "配饰", "透明蕾丝大腿饰链套装", "大腿链、蕾丝与透明结构", "sheer lace thigh jewelry|thigh chain|lace leg frame|completed static jewelry", part="配饰", materials="金属|网纱|丝", accessories="大腿链|蕾丝腿饰")

    # Fantasy themes.
    add("ghost_lace_sheer_gown", "情趣内衣", "幽灵蕾丝透明长裙", "幽灵感薄纱、残破蕾丝和长拖尾", "ghost lace gown|sheer long gown|tattered lace|flowing train", accessories="残破蕾丝|长拖尾")
    add("mothwing_tulle_lace_set", "情趣内衣", "蛾翼薄纱蕾丝套装", "蛾翼轮廓、毛绒边和透明层", "mothwing tulle set|lace accents|sheer layers|fuzzy trim", accessories="蛾翼结构|毛绒边")
    add("spiderweb_transparent_lace_set", "情趣内衣", "蛛网透明蕾丝套装", "蛛网蕾丝与身体连接结构", "spiderweb lace set|transparent body lace|connector straps|sheer lingerie", part="内衣", intensity="极限", accessories="蛛网蕾丝|连接带")
    add("moonveil_sheer_lace_dress", "情趣内衣", "月纱透明蕾丝长裙", "银色薄纱、面纱和高腰长裙", "moonveil lace dress|silver tulle|sheer veil|high-waist long dress", materials="网纱|丝", accessories="薄纱面纱|高腰长裙")

    # Erotic formal gowns.
    add("lace_corset_open_back_ball_gown", "情趣礼服", "蕾丝露背束腰舞会礼服", "舞会大裙摆与露背蕾丝束腰", "lace corset ball gown|open back|ball skirt|sheer lace panels", accessories="蕾丝束腰|露背结构")
    add("sheer_lace_high_slit_gown", "情趣礼服", "透明蕾丝高开衩礼服", "长裙轮廓、高开衩和透明蕾丝层", "sheer lace gown|high slit|transparent lace|long evening gown", accessories="高开衩|透明蕾丝层")
    add("tulle_detachable_bustle_gown", "情趣礼服", "薄纱可拆裙撑礼服", "可拆裙撑、长拖尾和透明外裙", "detachable bustle gown|tulle overskirt|long train|sheer formal gown", accessories="可拆裙撑|长拖尾")
    add("lace_illusion_shoulder_gown", "情趣礼服", "蕾丝幻影肩纱礼服", "肩部透视、蕾丝胸衣和长裙", "lace illusion shoulder gown|sheer shoulders|lace bodice|formal gown", accessories="肩纱|蕾丝胸衣")
    add("sheer_corset_tuxedo_gown", "情趣礼服", "透明束腰燕尾礼服", "燕尾结构、束腰与透明裤裙层", "sheer tuxedo gown|corset waist|tail coat|transparent skirt layer", materials="网纱|丝", accessories="燕尾|束腰")
    add("lace_open_waist_overskirt_gown", "情趣礼服", "蕾丝开腰外裙礼服", "开放腰部与可拆蕾丝外裙", "lace overskirt gown|open waist|detachable lace skirt|formal gown", accessories="开腰结构|可拆外裙")
    add("tulle_front_open_cape_gown", "情趣礼服", "薄纱前开披肩礼服", "前开披肩、贴身内裙和外层拖尾", "tulle cape gown|front-open cape|fitted underdress|formal train", accessories="前开披肩|外层拖尾")
    add("lace_body_jewelry_frame_gown", "情趣礼服", "蕾丝身体饰品框架礼服", "蕾丝与身体饰品框整合", "lace body jewelry gown|jewelry frame|lace connectors|formal gown", materials="网纱|金属|丝", accessories="身体饰品框|蕾丝连接")

    # Erotic bridal.
    add("lace_corset_wedding_bodysuit", "情趣婚纱", "蕾丝束腰婚礼连体衣", "婚礼场景与蕾丝束腰连体衣", "lace wedding bodysuit|bridal corset|sheer lace|wedding lingerie", part="内衣", accessories="蕾丝束腰|婚礼内层")
    add("sheer_tulle_wedding_overskirt", "情趣婚纱", "透明薄纱婚礼外裙", "婚礼外裙、极长薄纱和开放内层", "sheer wedding overskirt|long tulle skirt|open underlayer|bridal", part="下装", accessories="薄纱外裙|长拖尾")
    add("open_back_lace_wedding_gown", "情趣婚纱", "露背蕾丝婚纱", "正式婚纱轮廓与大面积露背", "open-back lace wedding gown|bridal lace|deep back opening|wedding dress", accessories="露背结构|蕾丝长裙")
    add("detachable_bridal_train_set", "情趣婚纱", "可拆新娘拖尾套装", "主裙与独立蕾丝拖尾", "detachable bridal train|lace train|wedding dress set|bridal layers", accessories="可拆拖尾|主裙")
    add("bridal_lace_keyhole_gown", "情趣婚纱", "新娘蕾丝锁孔长裙", "胸前锁孔、蕾丝长袖和长裙", "bridal lace keyhole gown|front keyhole|lace sleeves|long wedding dress", accessories="锁孔前胸|蕾丝长袖")
    add("sheer_tulle_bridal_cape_set", "情趣婚纱", "薄纱新娘披肩套装", "披肩、透明内层和新娘场景", "sheer bridal cape|tulle cape set|sheer underlayer|bridal", accessories="薄纱披肩|透明内层")
    add("lace_garter_wedding_dress", "情趣婚纱", "蕾丝吊袜婚纱", "吊袜结构与婚礼长裙结合", "lace wedding dress|garter straps|bridal lingerie layer|long gown", accessories="吊袜带|婚礼长裙")
    add("transparent_bridal_lace_slip", "情趣婚纱", "透明新娘蕾丝吊带裙", "轻量新娘内裙和透明蕾丝层", "transparent bridal slip|ivory lace|sheer wedding slip|thin straps", part="内衣", accessories="透明蕾丝层|细吊带")

    # Erotic swimwear.
    add("lace_corset_bikini_set", "情趣泳装", "蕾丝束腰比基尼套装", "束腰结构与分体泳装", "lace corset bikini|waist corset swimsuit|two-piece swimwear|lace panels", part="泳装", accessories="束腰|分体泳装")
    add("sheer_tulle_beach_bodysuit", "情趣泳装", "薄纱海滩连体衣", "透明海滩连体与泳装轮廓", "sheer tulle beach bodysuit|beach swimsuit|transparent tulle|fitted beachwear", part="泳装")
    add("open_back_lace_monokini", "情趣泳装", "露背蕾丝单肩泳装", "单肩、露背和蕾丝拼接", "open-back lace monokini|one-shoulder swimsuit|lace panels|back cutout", part="泳装", accessories="单肩结构|露背裁片")
    add("cutout_lace_one_piece_swimsuit", "情趣泳装", "镂空蕾丝连体泳装", "镂空裁片与蕾丝覆盖", "cutout lace swimsuit|one-piece swimsuit|lace windows|side cutouts", part="泳装", accessories="镂空裁片|蕾丝覆盖")
    add("transparent_panel_swim_dress", "情趣泳装", "透明拼片泳裙", "泳裙轮廓与透明拼片", "transparent panel swim dress|sheer swim dress|swim skirt|mesh panels", part="泳装", accessories="透明拼片|泳裙")
    add("tulle_overlay_bikini_set", "情趣泳装", "薄纱罩层比基尼套装", "比基尼主体与薄纱外层", "tulle overlay bikini|bikini set|sheer tulle layer|beachwear", part="泳装")
    add("lace_waist_window_swimsuit", "情趣泳装", "蕾丝腰部视窗泳装", "腰部视窗与泳装裙摆", "lace waist-window swimsuit|waist cutout|lace trim|swim dress", part="泳装", accessories="腰部视窗|泳装裙摆")
    add("bridal_white_sheer_swimsuit", "情趣泳装", "新娘白薄纱泳装", "白色婚礼色系与透明泳装", "white bridal swimsuit|sheer tulle swimwear|ivory swimsuit|bridal beachwear", part="泳装")

    # Pantyhose.
    add("lace_top_sheer_pantyhose", "袜", "蕾丝袜口薄透裤袜", "蕾丝袜口与薄透裤袜主体", "lace top pantyhose|sheer pantyhose|lace waistband|legwear", part="袜", accessories="蕾丝袜口")
    add("scalloped_lace_pantyhose", "袜", "波浪边蕾丝裤袜", "波浪边蕾丝与薄透裤袜结构", "scalloped lace pantyhose|sheer pantyhose|lace details|legwear", part="袜")
    add("floral_lace_pantyhose", "袜", "花卉蕾丝满版裤袜", "满版花卉蕾丝纹样与半透明腿部轮廓", "floral lace pantyhose|sheer legwear|flower lace pattern", part="袜")
    add("double_layer_tulle_pantyhose", "袜", "双层薄纱裤袜", "两层薄纱叠置、脚踝处密度变化", "double layer tulle pantyhose|sheer legwear|layered tulle", part="袜")
    add("ribbon_lace_pantyhose", "袜", "缎带蕾丝裤袜", "缎带与蕾丝袜口组合的薄透裤袜", "ribbon lace pantyhose|satin ribbon|lace top|sheer legwear", part="袜", materials="丝|网纱", accessories="缎带|蕾丝袜口")
    add("lace_waist_pantyhose", "袜", "蕾丝高腰裤袜", "蕾丝高腰结构与薄透裤袜", "lace waist pantyhose|high-waist legwear|sheer pantyhose|lace waistband", part="袜")
    add("distressed_lace_pantyhose", "袜", "破损蕾丝裤袜", "自然破洞、抽丝与蕾丝袜口", "distressed lace pantyhose|ripped sheer legwear|lace waistband", part="袜")
    add("crotchless_lace_pantyhose", "袜", "开裆蕾丝裤袜", "高腰蕾丝袜口、完整腿部包覆与开放裆部", "crotchless lace pantyhose|open lower panel|sheer legwear|lace waistband", part="袜", intensity="极限", accessories="开裆结构")

    # Thigh-highs.
    add("black_lace_cuff_thighhigh", "袜", "黑色蕾丝袜口过膝袜", "黑色过膝袜与蕾丝袜口", "black thighhighs|lace cuffs|over-knee socks|legwear", part="袜")
    add("sheer_overknee_lace_socks", "袜", "透明蕾丝过膝袜", "透明蕾丝主体与过膝轮廓", "sheer over-knee socks|lace socks|transparent legwear", part="袜")
    add("ribbon_thighhigh_stockings", "袜", "缎带装饰大腿袜", "缎带袜口与半透明大腿袜", "ribbon thighhighs|satin ribbon|sheer stockings|legwear", part="袜", materials="丝|网纱", accessories="缎带袜口")
    add("scalloped_lace_thighhigh", "袜", "波浪边蕾丝大腿袜", "波浪边蕾丝袜口和贴合大腿轮廓", "scalloped lace thighhighs|lace cuffs|sheer stockings", part="袜")
    add("thigh_window_lace_stockings", "袜", "大腿视窗蕾丝袜", "大腿外侧视窗与蕾丝连接带", "thigh-window stockings|lace garter|cutout legwear|sheer stockings", part="袜", accessories="大腿视窗|连接带")
    add("bridal_tulle_thighhigh", "袜", "新娘薄纱大腿袜", "白色婚礼色系、薄纱层与蕾丝袜口", "bridal thighhighs|white tulle stockings|lace cuffs|wedding legwear", part="袜", materials="网纱|丝")

    # Bodystockings.
    add("high_neck_lace_bodystocking", "袜", "高领蕾丝连身袜", "高领、长袖与蕾丝连身袜主体", "high-neck lace bodystocking|long sleeves|sheer body stocking|lace", part="内衣")
    add("open_back_tulle_bodystocking", "袜", "薄纱露背连身袜", "薄纱主体、露背和高开衩结构", "open-back bodystocking|sheer tulle|high-cut body stocking|legwear", part="内衣", accessories="露背结构|高开衩")
    add("corset_lace_bodystocking", "袜", "束腰蕾丝连身袜", "束腰轮廓与蕾丝连身袜组合", "corset bodystocking|lace body stocking|waist shaping|legwear", part="内衣", materials="网纱|金属|丝", accessories="束腰结构")
    add("open_lower_lace_bodystocking", "袜", "开放下装蕾丝连身袜", "完整腿部包覆与开放下装结构", "open-lower bodystocking|lace legwear|open lower panel", part="内衣", intensity="极限", accessories="开放下装")

    # Open-nipple garments.
    add("open_nipple_lace_halter", "情趣内衣", "乳尖开放蕾丝挂脖", "挂脖轮廓不覆盖乳尖，保留蕾丝连接", "open nipple lace halter|uncovered nipples|lace connectors|halter top", part="上装", intensity="极限", accessories="开放乳尖|蕾丝连接")
    add("open_nipple_sheer_blouse", "日常服装", "乳尖开放透明衬衫", "透明衬衫保留完整上装轮廓但不覆盖乳尖", "open nipple sheer blouse|uncovered nipples|transparent shirt|lace trim", part="上装", intensity="极限", materials="网纱|棉", accessories="开放乳尖|蕾丝边")
    add("open_nipple_lace_cutout_dress", "情趣礼服", "乳尖开放蕾丝镂空裙", "蕾丝裙轮廓与开放乳尖结构", "open nipple lace dress|uncovered nipples|lace cutout dress|formal silhouette", intensity="极限", accessories="开放乳尖|蕾丝镂空")
    add("open_nipple_tulle_babydoll", "内衣/睡衣", "乳尖开放薄纱睡裙", "薄纱睡裙保留裙摆与肩带，不覆盖乳尖", "open nipple tulle babydoll|uncovered nipples|sheer nightgown|thin straps", part="内衣", intensity="极限", accessories="开放乳尖|薄纱下摆")
    add("open_nipple_lace_corset", "情趣内衣", "乳尖开放蕾丝束腰", "蕾丝束腰结构不覆盖乳尖", "open nipple lace corset|uncovered nipples|lace corset|waist structure", part="内衣", intensity="极限", materials="网纱|金属|丝", accessories="开放乳尖|束腰")
    add("open_nipple_sheer_gown", "情趣礼服", "乳尖开放透明礼服", "长礼服轮廓与开放乳尖结构", "open nipple sheer gown|uncovered nipples|transparent gown|formal train", intensity="极限", accessories="开放乳尖|长拖尾")
    add("open_nipple_lace_swimsuit", "情趣泳装", "乳尖开放蕾丝泳装", "泳装轮廓不覆盖乳尖，保留蕾丝与水中场景", "open nipple lace swimsuit|uncovered nipples|sheer swimsuit|water scene", part="泳装", intensity="极限", accessories="开放乳尖|蕾丝覆盖")
    add("open_nipple_tulle_wedding_dress", "情趣婚纱", "乳尖开放薄纱婚纱", "婚礼长裙与薄纱结构不覆盖乳尖", "open nipple bridal gown|uncovered nipples|sheer wedding dress|tulle train", intensity="极限", accessories="开放乳尖|薄纱拖尾")

    # Open-lower garments.
    add("open_lower_lace_skirt_set", "情趣内衣", "阴部开放蕾丝裙套装", "蕾丝裙轮廓与开放下装区域", "open lower lace skirt set|uncovered intimate area|lace skirt|lingerie set", part="内衣", intensity="极限", accessories="开放下装|蕾丝裙")
    add("open_lower_tulle_gown", "情趣礼服", "阴部开放薄纱长裙", "薄纱长裙轮廓与开放下装区域", "open lower tulle gown|uncovered intimate area|sheer long gown|formal train", intensity="极限", accessories="开放下装|薄纱长裙")
    add("open_lower_sheer_wedding_dress", "情趣婚纱", "阴部开放透明婚纱", "婚纱长裙与开放下装区域", "open lower sheer wedding dress|uncovered intimate area|transparent bridal gown|lace train", intensity="极限", accessories="开放下装|蕾丝拖尾")
    add("open_lower_lace_corset_dress", "情趣礼服", "阴部开放蕾丝束腰裙", "蕾丝束腰裙与开放下装结构", "open lower lace corset dress|uncovered intimate area|lace corset|formal skirt", intensity="极限", materials="网纱|金属|丝", accessories="开放下装|蕾丝束腰")
    add("open_lower_tulle_babydoll", "内衣/睡衣", "阴部开放薄纱睡裙", "薄纱睡裙保留上装与裙摆，下装区域开放", "open lower tulle babydoll|uncovered intimate area|sheer nightgown|soft hem", part="内衣", intensity="极限", accessories="开放下装|薄纱裙摆")
    add("open_lower_lace_swimsuit", "情趣泳装", "阴部开放蕾丝泳装", "泳装主体与开放下装区域", "open lower lace swimsuit|uncovered intimate area|lace swimwear|water scene", part="泳装", intensity="极限", accessories="开放下装|蕾丝覆盖")
    add("open_lower_tulle_bikini_skirt", "情趣泳装", "阴部开放薄纱比基尼裙", "比基尼裙轮廓、薄纱层与开放下装区域", "open lower bikini skirt|uncovered intimate area|tulle beach skirt|bikini set", part="泳装", intensity="极限", accessories="开放下装|薄纱裙")
    add("open_lower_lace_jumpsuit", "情趣内衣", "阴部开放蕾丝连体裤", "蕾丝连体裤轮廓与开放下装区域", "open lower lace jumpsuit|uncovered intimate area|lace jumpsuit|body-focused outfit", intensity="极限", accessories="开放下装|蕾丝连体裤")

    # Dual-open garments.
    add("dual_open_lace_dress", "情趣礼服", "上下双开放蕾丝裙", "乳尖与阴部区域保持开放，蕾丝只保留外轮廓", "dual open lace dress|uncovered nipples|uncovered intimate area|minimal lace connectors", intensity="极限", accessories="上下开放|极简蕾丝连接")
    add("dual_open_tulle_gown", "情趣礼服", "上下双开放薄纱礼服", "薄纱礼服轮廓与上下开放区域", "dual open tulle gown|uncovered nipples|uncovered intimate area|sheer formal gown", intensity="极限", accessories="上下开放|薄纱长裙")
    add("dual_open_sheer_swimsuit", "情趣泳装", "上下双开放透明泳装", "透明泳装外轮廓与上下开放区域", "dual open sheer swimsuit|uncovered nipples|uncovered intimate area|water scene", part="泳装", intensity="极限", accessories="上下开放|透明泳装")
    add("dual_open_lace_wedding_dress", "情趣婚纱", "上下双开放蕾丝婚纱", "蕾丝婚纱轮廓与上下开放区域", "dual open lace wedding dress|uncovered nipples|uncovered intimate area|bridal lace", intensity="极限", accessories="上下开放|蕾丝拖尾")

    return items
