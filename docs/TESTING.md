# 测试记录

- 运行环境：Python 3.13（隔离 venv），Windows
- 执行命令：`python -m unittest discover -s tests`
- 结果：**179 项全部通过**
- 测试时间：2026-10-21（基础）/ 2026-10-22（外送链路、套餐口味）/ 2026-10-23（麦历改名、奏折卡片、禁译与点选、金额单位、外送默认、门店定位与官方距离、开场四项、街道级关键词、Skill 渐进式披露）

---

## 一、测试结果总表

| # | 场景 | 用例 | 结果 |
|---|---|---|:---:|
| 1 | 普通日期，没有节日主题 | `test_01_normal_day_no_festival` | ✅ 通过 |
| 2 | 命中某个二十四节气 | `test_02_solar_term_hit`（2026-10-23 霜降） | ✅ 通过 |
| 3 | 命中传统节日 | `test_03_traditional_festival_hit`（2026-09-25 中秋） | ✅ 通过 |
| 4 | 日期数据异常或不可用 | `test_04_calendar_data_unavailable` / `test_04b` | ✅ 通过 |
| 5 | 节日主题推荐餐品当前不可售 | `test_15_theme_item_unavailable` | ✅ 通过 |
| 6 | 用户预算与主题推荐冲突 | `test_13_budget_conflict` | ✅ 通过 |
| 7 | 优惠查询失败 | `test_17_coupon_query_failed` | ✅ 通过 |
| 8 | 官方价格核验失败 | `test_21_price_verification_failed` | ✅ 通过 |
| 9 | 用户明确表示不喜欢当前主题 | `test_09_user_can_opt_out_theme` | ✅ 通过 |
| 10 | 输出中不得出现虚构内容 | `test_29_no_fabricated_names_or_prices` | ✅ 通过 |
| 11 | MCP 菜单返回为空 | `test_12_empty_menu_degrades` | ✅ 通过 |
| 12 | 麦历只做娱乐彩蛋（不预测吉凶/不影响决策/不冒充官方促销） | `test_07_maicalendar_is_entertainment_only`（9月全月扫描） | ✅ 通过 |
| 13 | 用户偏好区分明示/推测 | `test_25_explicit_vs_inferred` | ✅ 通过 |
| 14 | 偏好清除 | `test_26_clear_preference` / `test_27_clear_all` | ✅ 通过 |
| 15 | 不夸大跨会话记忆 | `test_28_no_overclaim_persistence` | ✅ 通过 |
| 16 | 禁止交易操作 | `test_31_no_side_effect_tools_in_source`（源码扫描） | ✅ 通过 |
| 17 | 指定日期须标明模拟 | `test_32_render_marks_simulated_date` | ✅ 通过 |
| 18 | 不得宣称绝对最低价 | `test_24_no_absolute_lowest_claim` | ✅ 通过 |
| 19 | 真实官方核价解析 | `test_22_real_official_price`（4100 分 = 41.00 元） | ✅ 通过 |
| 20 | 未核价方案须标记 | `test_23_unverified_price_marked` | ✅ 通过 |
| 21 | 券门槛过滤 | `test_20_threshold_filters` | ✅ 通过 |
| 22 | 未核实券不承诺可用 | `test_19_unverified_coupon_not_promised` | ✅ 通过 |
| 23 | 官方返回空券列表 | `test_18_empty_coupon_list` | ✅ 通过 |
| 24 | 忌口剔除 | `test_14_dislike_filters` | ✅ 通过 |
| 25 | 官方未返回价格须标注 | `test_16_unknown_price_flagged` | ✅ 通过 |
| 26 | 合法节假日来自年度数据 | `test_06_legal_holiday_from_official_data` | ✅ 通过 |
| 27 | 节气区间排序回归 | `test_05_solar_term_boundary_sort` | ✅ 通过 |
| 28 | 主题可稳定复现 | `test_08_theme_deterministic` | ✅ 通过 |
| 29 | 主题不得包装成官方促销 | `test_10_theme_not_claimed_as_official` | ✅ 通过 |
| 30 | 合规自检能识别夸大表述 | `test_30_compliance_scan_flags_claims` | ✅ 通过 |
| 31 | 真实菜单 fixture 来源校验 | `test_33_menu_fixture_is_real` | ✅ 通过 |
| 32 | 真实核价 fixture 来源校验 | `test_34_price_fixture_is_real` | ✅ 通过 |
| 33 | 真实返回结构适配 | `test_35_adapter_handles_real_shape` | ✅ 通过 |
| 34 | 候选方案均来自真实数据 | `test_11_basic_recommendation_uses_real_data` | ✅ 通过 |
| 35 | 合规自检（渲染产物） | `render` 端到端输出 | ✅ 通过 |
| 36 | 章节编号与降级渲染 | `render` 端到端输出 | ✅ 通过 |
| 37 | 外送关键词识别 | `test_36_delivery_keywords` | ✅ 通过 |
| 38 | 到店识别 + 未言明时标注为推断 | `test_37_dine_in_default_and_explicit` | ✅ 通过 |
| 39 | 得来速/团餐标记为未实现 | `test_38_unimplemented_scenes_flagged` | ✅ 通过 |
| 40 | 显式场景优先于文本推断 | `test_39_explicit_overrides_text` | ✅ 通过 |
| 41 | 真实空地址簿优雅降级、不自动创建 | `test_40_real_empty_addresses_degrades_gracefully` | ✅ 通过 |
| 42 | 外送缺 `beCode` 必须阻塞（引用真实 600048） | `test_41_becode_required_evidence` | ✅ 通过 |
| 43 | `addressId` 不得编造 | `test_42_address_id_must_come_from_official` | ✅ 通过 |
| 44 | 打通后 `query-meals` 参数正确（含 beCode） | `test_43_ready_path_builds_correct_params` | ✅ 通过 |
| 45 | 配送费不臆测 | `test_44_delivery_fees_never_guessed` | ✅ 通过 |
| 45b | 外送无起送门槛：只说明、不给金额、不标未核实 | `test_44b_delivery_has_no_minimum_order_fee` | ✅ 通过 |
| 46 | 驿站传膳章节明示不自动下单 | `test_45_delivery_section_never_claims_auto_order` | ✅ 通过 |
| 47 | 外送未打通须标注到店口径，不冒充外送报价 | `test_46b_blocked_delivery_marks_dine_in_menu_mismatch` | ✅ 通过 |
| 48 | 奏折含外送章节 | `test_46_render_includes_delivery_section` | ✅ 通过 |
| 49 | 偏好跨会话存档与读回 | `test_47_persist_and_reload_across_sessions` | ✅ 通过 |
| 50 | 清除偏好须删除存档文件 | `test_48_clear_all_removes_file` | ✅ 通过 |
| 51 | 存档成功须改口「跨会话有效」 | `test_49_persisted_scope_is_declared` | ✅ 通过 |
| 52 | 存档文件损坏须降级 | `test_50_corrupted_file_degrades` | ✅ 通过 |
| 53 | 存档路径须在工作区之外 | `test_51_storage_outside_workspace` | ✅ 通过 |
| 54 | 解析真实可领券文本 | `test_52_parses_real_text_response` | ✅ 通过 |
| 55 | 空文本不得编造券名 | `test_53_empty_text_not_fabricated` | ✅ 通过 |
| 56 | 可领券须标注非本单可用、臣不代领 | `test_54_render_marks_not_usable_for_this_order` | ✅ 通过 |
| 57 | 真实外送菜单价格 | `test_55_real_delivery_menu_prices_differ_from_dine_in` | ✅ 通过 |
| 58 | 真实外送核价含配送费/打包费 | `test_56_real_delivery_price_includes_fees` | ✅ 通过 |
| 59 | 核价核验兼容原始返回 | `test_57_verify_price_accepts_raw_response` | ✅ 通过 |
| 60 | 奏折展示费用明细 | `test_58_render_shows_fee_breakdown` | ✅ 通过 |
| 61 | fixture 不得残留个人身份信息 | `test_59_fixtures_must_not_leak_personal_data` | ✅ 通过 |
| 62 | 菜单列表接口确实不返回图片 | `test_60_query_meals_has_no_image_field` | ✅ 通过 |
| 63 | 单品详情适配（含图片、可特调） | `test_61_meal_detail_adapts_real_single` | ✅ 通过 |
| 64 | 套餐详情解析默认搭配 | `test_62_meal_detail_adapts_real_combo` | ✅ 通过 |
| 65 | 图片只回填官方返回，不复用他品之图 | `test_63_attach_photos_only_from_official_return` | ✅ 通过 |
| 66 | 图鉴渲染为 Markdown 图片并标注来源 | `test_64_gallery_renders_markdown_image` | ✅ 通过 |
| 67 | 无图时不编造链接 | `test_65_gallery_without_photos_never_fabricates` | ✅ 通过 |
| 68 | 奏折含「御膳图鉴」章节 | `test_66_memorial_gallery_section` | ✅ 通过 |
| 69 | 特调项默认不主动展开（遵官方规则） | `test_67_meal_detail_card_respects_official_display_rule` | ✅ 通过 |
| 70 | 详情无图时如实说明 | `test_68_missing_image_is_reported_not_invented` | ✅ 通过 |
| 71 | 三档写操作互不重叠，下单在最严档 | `test_31b_write_tiers_are_separated` | ✅ 通过 |
| 72 | 领券默认不自动执行 | `test_69_default_is_never_auto_claim` | ✅ 通过 |
| 73 | 确认前须逐张复述券名 | `test_70_confirm_prompt_lists_every_coupon` | ✅ 通过 |
| 74 | 如实声明「只能全领不能挑」 | `test_71_cannot_choose_single_coupon_is_disclosed` | ✅ 通过 |
| 75 | 领券不等于本单可用，须回查+核价 | `test_72_claim_does_not_promise_usable_for_this_order` | ✅ 通过 |
| 76 | 未核实领取资格须如实标注 | `test_73_unknown_claim_quota_is_disclosed` | ✅ 通过 |
| 77 | 无可领券时不得生成代领动作 | `test_74_nothing_to_claim_does_not_execute` | ✅ 通过 |
| 78 | 奏折出现代领确认段，且不冲掉不下单底线 | `test_75_memorial_shows_claim_section` | ✅ 通过 |
| 79 | 首个非空门店券返回解析出适用商品编码 | `test_76_store_coupons_adapts_real_non_empty` | ✅ 通过 |
| 80 | 空券是真实结果，不得当成查询失败 | `test_77_empty_store_coupons_is_not_a_failure` | ✅ 通过 |
| 81 | 券效核验引用官方两次核价，不自行算价 | `test_78_coupon_price_verified_by_two_official_calls` | ✅ 通过 |
| 82 | 基线不可用时不得断言减免金额 | `test_79_baseline_unavailable_is_not_guessed` | ✅ 通过 |
| 83 | 未做对照核价时只引用官方 discount | `test_80_no_baseline_still_reports_official_discount` | ✅ 通过 |
| 84 | 领券 3 张 vs 卡包 2 张的差异如实对账 | `test_81_claim_reconciliation_reports_real_mismatch` | ✅ 通过 |
| 85 | 对账一致时正确判为一致 | `test_82_claim_reconciliation_consistent_case` | ✅ 通过 |
| 86 | 奏折渲染券核验三章，且券码不入输出 | `test_83_memorial_renders_coupon_verification` | ✅ 通过 |
| 87 | 缺门店编码不得下单 | `test_84_blocked_without_store_code` | ✅ 通过 |
| 88 | 空单不得创建 | `test_85_blocked_with_empty_items` | ✅ 通过 |
| 89 | 无官方核价不得下单 | `test_86_blocked_without_official_price` | ✅ 通过 |
| 90 | 到店单缺 takeWayCode 不得臆测 | `test_87_pickup_blocked_without_take_way_code` | ✅ 通过 |
| 91 | 外送单缺 addressId 不得下单 | `test_88_delivery_blocked_without_address_id` | ✅ 通过 |
| 92 | 只确认部分复述仍不得出单 | `test_89_need_confirm_until_all_three_recitals` | ✅ 通过 |
| 93 | 三重复述齐备才可出单，且「臣绝不代付」写死 | `test_90_ready_only_after_all_three_and_never_pays` | ✅ 通过 |
| 94 | 奏折渲染「拟旨下单」，就绪时改口径仍不代付 | `test_91_memorial_renders_order_section` | ✅ 通过 |
| 95 | 未获全确认时奏折维持「未下单、未付款」 | `test_92_memorial_keeps_default_when_order_not_ready` | ✅ 通过 |
| 96 | 可乐冰量识别为「必选」组，默认标准 | `test_93_cola_has_required_ice_group` | ✅ 通过 |
| 97 | 必选口味未定不得落单 | `test_94_unconfirmed_required_taste_blocks_order` | ✅ 通过 |
| 98 | 陛下定了去冰须写进复述 | `test_95_chosen_taste_is_written_into_recital` | ✅ 通过 |
| 99 | 套餐未逐轮定夺不得落单，并摆出官方默认 | `test_96_combo_without_round_selections_blocks_order` | ✅ 通过 |
| 100 | 只定部分轮次不得替陛下补齐 | `test_97_partial_rounds_block_order` | ✅ 通过 |
| 101 | 三轮齐全时复述逐轮写出 | `test_98_full_rounds_render_every_choice` | ✅ 通过 |
| 102 | 下单前待定清单逐条列出该问什么 | `test_99_checklist_lists_what_to_ask` | ✅ 通过 |
| 103 | `minValues=0` 的可选项不拦下单 | `test_100_optional_mods_do_not_block` | ✅ 通过 |
| 104 | 奏折首栏叫「麦历呈报」，不得再出现「黄历」「钦天监」 | `test_105_heading_is_maicalendar_not_huangli` | ✅ 通过 |
| 105 | 麦历三条边界一句不少（不预测吉凶/不影响决策/不冒充官方促销） | `test_106_disclaimer_states_all_three_boundaries` | ✅ 通过 |
| 106 | 改名不得改掉二十四节气与传统节日 | `test_107_solar_terms_and_festivals_are_kept` | ✅ 通过 |
| 107 | 全年 365 天扫描，输出不得冒出「黄历」「钦天监」「宜忌」「吉日」 | `test_108_no_huangli_wording_across_a_full_year` | ✅ 通过 |
| 108 | 陛下关闭主题时，说明也用「麦历」说法 | `test_109_opt_out_says_maicalendar_not_huangli` | ✅ 通过 |
| 109 | 奏折卡片含竖排标题、朱印与「臣绝不代付」 | `test_110_scroll_has_title_seal_and_never_pays` | ✅ 通过 |
| 110 | 卡片金额两位小数、图片官方 CDN、麦历三条边界齐全 | `test_111_scroll_prices_and_photos_from_official` | ✅ 通过 |
| 111 | 卡片脱敏：券码/手机号/地址 ID 塞进去也要被隐去 | `test_112_scroll_desensitizes_sensitive_ids` | ✅ 通过 |
| 112 | 信息不全时卡片列缺什么，不出可下单口径 | `test_113_blocked_plan_renders_blockers_not_ready` | ✅ 通过 |
| 113 | 三重复述齐备时逐项标「已确认」 | `test_114_ready_scroll_shows_confirmed_marks` | ✅ 通过 |
| 114 | 餐品名带尖括号不得破坏卡片结构 | `test_115_scroll_escapes_hostile_names` | ✅ 通过 |
| 115 | 门店翻成「面馆」必须被扫出 | `test_116_store_must_not_become_noodle_shop` | ✅ 通过 |
| 116 | 门店/餐厅/麦乐送等正常用词不得误伤 | `test_117_clean_text_passes` | ✅ 通过 |
| 117 | 禁译表每个词都要能被抓到 | `test_118_all_banned_words_are_caught` | ✅ 通过 |
| 118 | 奏折卡片要有章节排版，不能是裸图片列表 | `test_119_scroll_has_real_layout_not_bare_image_list` | ✅ 通过 |
| 119 | 图片走网格排版且只引官方 CDN | `test_120_scroll_photos_laid_out_in_grid` | ✅ 通过 |
| 120 | 陛下不必打字：卡片须给可点选项按钮 | `test_121_scroll_offers_clickable_picks` | ✅ 通过 |
| 121 | 卡片须载麦历三边界与「臣绝不代付」 | `test_122_scroll_states_boundaries_and_never_pays` | ✅ 通过 |
| 122 | 卡片不得出现业态错译 | `test_123_scroll_no_mistranslation` | ✅ 通过 |
| 123 | 下单卡片选项随状态走 | `test_124_order_scroll_picks_follow_status` | ✅ 通过 |
| 124 | 分与元不得混用（同一数值两种结果） | `test_125_fen_and_yuan_are_not_confused` | ✅ 通过 |
| 125 | 把「元」当「分」再除一次须被判异常（真实 bug） | `test_126_double_conversion_is_caught` | ✅ 通过 |
| 126 | 正常金额不得被误伤 | `test_127_reasonable_prices_pass` | ✅ 通过 |
| 127 | 卡片餐品价必须是元（9.50），不能是分（0.10） | `test_128_scroll_shows_yuan_prices_not_cents` | ✅ 通过 |
| 128 | 陛下未言明时默认麦乐送外送 | `test_129_default_scene_is_delivery` | ✅ 通过 |
| 129 | 陛下明说到店自取不得被默认覆盖 | `test_130_explicit_pickup_still_wins` | ✅ 通过 |
| 130 | 门店查询须城市+地段齐备，否则问陛下 | `test_131_store_query_needs_city_and_keyword` | ✅ 通过 |
| 131 | 须如实写明官方无经纬度、不读 IP | `test_132_store_query_declares_no_geolocation` | ✅ 通过 |
| 132 | 奏折呈上后必须给选项（after_memorial） | `test_133_after_memorial_offers_options` | ✅ 通过 |
| 133 | 下单确认只问还没点头的那几项 | `test_134_order_confirm_lists_pending_recitals` | ✅ 通过 |
| 134 | 必选口味与用膳方式都要给选项 | `test_135_ice_and_scene_have_options` | ✅ 通过 |
| 135 | 任何阶段都得有得选，不能让陛下干瞪眼 | `test_136_picks_never_returns_empty` | ✅ 通过 |
| 136 | 地址文本能切出城市与区县（含直辖市） | `test_137_parse_city_and_district_from_address` | ✅ 通过 |
| 137 | 直辖市地址解析正确 | `test_138_parse_direct_city` | ✅ 通过 |
| 138 | 切不出的地址不得臆造，只切出城市则降级 | `test_139_unparsable_address_is_not_invented` | ✅ 通过 |
| 139 | 从真实地址 fixture 反推出杭州·上城区 | `test_140_guess_from_real_address_fixture` | ✅ 通过 |
| 140 | 有地址 → need_confirm + 点选项，未确认不发查询 | `test_141_addr_book_gives_confirm_not_question` | ✅ 通过 |
| 141 | 陛下明说地段 > 地址反推 | `test_142_explicit_area_beats_guess` | ✅ 通过 |
| 142 | 无地址才退回提问 | `test_143_no_address_falls_back_to_ask` | ✅ 通过 |
| 143 | 如实写明"臣无 IP、接口无经纬度" | `test_144_ip_geolocation_is_honestly_disclaimed` | ✅ 通过 |
| 144 | store_area 阶段永远可点选 | `test_145_store_area_picks_always_clickable` | ✅ 通过 |
| 145 | 官方 distance 已由近及远排好，取 nearest 正确 | `test_146_official_returns_distance_already_sorted` | ✅ 通过 |
| 146 | 距离显示米/公里，异常值不臆造 | `test_147_distance_display_is_sane` | ✅ 通过 |
| 147 | 门店清单展示距离与完整 storeCode | `test_148_store_list_shows_distance_and_store_code` | ✅ 通过 |
| 148 | distance 非法/缺失时不得估算 | `test_149_bad_distance_is_not_invented` | ✅ 通过 |
| 149 | 空门店列表与接口报错如实上报 | `test_150_empty_store_list_is_reported_honestly` | ✅ 通过 |
| 150 | 开场四项且全部可点 | `test_151_opening_has_four_clickable_options` | ✅ 通过 |
| 151 | 「按预算拟单」「今日推荐」恒在前两位、不可换序 | `test_152_two_required_options_come_first` | ✅ 通过 |
| 152 | 头一问不得退化成开放式填空 | `test_153_opening_is_never_an_open_question` | ✅ 通过 |
| 153 | opening 阶段已登记进选项表 | `test_154_opening_stage_in_picks_registry` | ✅ 通过 |
| 154 | 地址须切到街道门牌级，不停在区县 | `test_155_street_beats_district` | ✅ 通过 |
| 155 | 区县/城市级标 coarse，并把"给个更准的地标"排第一 | `test_156_district_only_is_flagged_coarse` | ✅ 通过 |
| 156 | 区县口径须明写"区中心离陛下可能很远" | `test_157_district_note_warns_explicitly` | ✅ 通过 |
| 157 | 最近门店超 1.5 公里 → 提示换关键词 | `test_158_far_result_triggers_refine_advice` | ✅ 通过 |
| 158 | 无门牌号时退到小区/大厦名 | `test_159_landmark_fallback_is_used` | ✅ 通过 |
| 159 | 核心 SKILL.md 保持瘦身（≤6500 字符 / ≤200 行） | `test_160_core_skill_stays_small` | ✅ 通过 |
| 160 | 第一步必须写明"本轮到此为止" | `test_161_stop_instruction_exists` | ✅ 通过 |
| 161 | 必须明令"按需取用、不要一次读完" | `test_162_no_lazy_preload_instruction` | ✅ 通过 |
| 162 | 七步子文件齐备且核心里有导航 | `test_163_workflow_files_exist_and_are_linked` | ✅ 通过 |
| 163 | 拆分后八条铁律与写操作分级一条不丢 | `test_164_red_lines_survive_the_split` | ✅ 通过 |
| 164 | 第一步必须自己写出提问工具名（不能只靠 voice.md） | `test_165_step1_names_the_question_tool` | ✅ 通过 |
| 165 | 必须警告：命令行编号文字是降级兜底 | `test_166_step1_warns_against_text_fallback` | ✅ 通过 |
| 166 | 铁律 7 要写出工具名，不能只说"选项卡片" | `test_167_red_line_7_names_the_tool` | ✅ 通过 |
| 167 | voice.md 读取时机须覆盖开场第一步 | `test_168_voice_read_timing_covers_opening` | ✅ 通过 |
| 168 | opening 返回自带 render_via / render_note | `test_169_opening_output_is_card_ready` | ✅ 通过 |
| 169 | 所有阶段都带"怎么呈"，不只开场 | `test_170_every_stage_carries_render_hint` | ✅ 通过 |
| 170 | CLI 编号文字须有横幅标明是兜底 | `test_171_cli_banner_marks_fallback` | ✅ 通过 |
| 171 | 开场必须正好三问，顺序为 何膳/用度人数/传膳与送处 | `test_172_bundle_has_exactly_three_questions` | ✅ 通过 |
| 172 | 第一问仍是原样四项，前两项固定不可换序 | `test_173_q1_keeps_four_options_and_order` | ✅ 通过 |
| 173 | 预算与人数必须是可点档位，不是留给陛下填空 | `test_174_budget_and_people_are_clickable_not_blank` | ✅ 通过 |
| 174 | 外送/自取与地址合成一问，否则又要多问一轮 | `test_175_scene_and_address_merged_into_one_question` | ✅ 通过 |
| 175 | 三问包自带「怎么呈」与停下指令 | `test_176_bundle_carries_render_hint_and_stop_note` | ✅ 通过 |
| 176 | 宿主不支持多问卡片时旧版单问仍在 | `test_177_single_mode_still_available` | ✅ 通过 |
| 177 | 两个新阶段进 picks 注册表 | `test_178_new_stages_registered` | ✅ 通过 |
| 178 | 可发布文件不得含住户单元级住址（×幢×室） | `test_60_publishable_files_must_not_carry_unit_level_address` | ✅ 通过 |

---

## 二、开发中发现并修复的真实缺陷

| 缺陷 | 现象 | 根因 | 修复 |
|---|---|---|---|
| 节气整体偏晚约 8.4 小时 | 2025 立春算成 2/4 06:20，实际应为 2/3 22:10 | `ephem.Ecliptic(Sun).lon` 返回相对 **J2000 平春分点**的黄经，与节气定义采用的**当日平春分点**差约 0.36° | 改用 apparent geocentric 赤道坐标 + 当日黄赤交角换算；已与 `next_equinox`/`next_solstice` 对 2025、2026 年 8 个分至点校验，误差 ≤1 分钟 |
| 「上一个节气」判断错误 | 霜降日（10/23）被判成"大寒"节气区间，主题错成"暖冬传膳" | 节气按传统顺序排列（立春→大寒），但公历日期非升序；小寒/大寒在 1 月却排在末尾，覆盖了正确结果 | `nearest_solar_term()` 内改为按日期升序排列 |
| 空券列表被误判为查询失败 | `{"coupons": []}` 返回"查询失败" | 用 `or` 短路，空列表被当成假值 | 显式 `is None` 判断，区分"无券"与"查询失败" |
| 合规自检误报 | 免责声明里的"保健/治疗"被判为违规 | 自检扫描了否定式免责文本 | 自检排除免责声明行，只扫主张性内容 |
| 奏折章节跳号 | 出现"一→二→三→六" | 章节号硬编码，条件区块不渲染时断号 | 改为动态计数器 |
| 外送阻塞时仍展示到店菜单 | 外送链路未打通，奏折却把 `beType=1` 的到店餐品当作外送候选呈现 | 菜单章节未校验场景口径一致性 | 外送 `status != ready` 时，菜单与核价章节强制加注"到店自取口径，不代表外送报价" |
| 餐品价显示成"0.10 元" | 奏折里餐品价格全是零点几元 | 同一代码里「分」(calculate-price)与「元」(query-meals 的 currentPrice 字符串)两套单位只靠变量名约定区分；奏折卡片把已是元的值当成分又除了一次 100 | 新增 fmt_money/safe_money 显式声明单位 + 合理性校验(0.5–2000 元)，越界即判换算错误并如实说「臣不敢以此报价」（测试 125–128 锁定） |
| 门店全都很远 | 陛下实测自取门店离得很远 | ①`query-nearby-stores` 的 searchType 默认 1 = 查**收藏餐厅**，不按位置；②（更深一层）keyword 只给到**区县**，区中心离陛下几公里 | ①一律改用 searchType=2；②**区县不得当"就近"**：`parse_address_location()` 一路切到路名+门牌，新增 `keyword_level` 四级与 `coarse_keyword` 标记，粗口径时改说"区中心离陛下可能很远"并把「给个更准的地标」排第一；③新增 `assess_nearby_result()`，最近门店 >1.5 公里即提示换关键词。实测同一查询点：区县 2545m → 地标 188m / 门牌 410m（测试 136–159 锁定） |
| **加载动辄二三十分钟** | 陛下反馈："这个 skill 的加载怎么时间那么长，有的时候甚至要 30 分钟" | **诊断**（先不改）：①脚本纯标准库、启动 0.70–0.79s（三次实测），排除；②目录仅 580K/38 文件，排除；③真正原因是**七步流程一次性注入**（SKILL.md 538 行 / 17,850 字符 ≈ 10,670 token，且**第一步无"停下"指令**），模型读到完整说明书会一路跑完 ≈12–15 次 MCP 往返 + 6–8 次 CLI；④SKILL.md 体量为次因（20 个已装 skill 里排第 2）；⑤模型只是放大器，换快模型也省不掉网络往返 | **改为渐进式披露**：七步拆到 `workflow/`、话术与券语义拆到 `references/`，核心 SKILL.md 瘦到 4,808 字符 ≈ **3,042 token（-71%）**；核心新增「按需取用、不要一次读完」与第一步末尾 🛑「本轮到此为止，陛下点选前不得读 workflow/、不得调 MCP」；由测试 160–164 锁住不许长回去 |
| 金额写成"6.0 元" | 配送费、应付总额等被 `round(分/100, 2)` 直接打印，出现"6.0 元""19.0 元"这种不像钱的写法 | 金额数值未经显示层格式化 | 新增 `_yuan()` 助手，显示层一律两位小数；下单复述、核价明细、券效章节统一口径（测试 58/90 锁定） |
| **点选退化成"陛下可回复：A／B／C"** | 陛下实测：技能说好四项可点，最后却把选项念成文字让人打字 | **主因：SKILL.md 第一步只写"四项全部可点"，全篇没写用哪个工具呈卡片**；唯一写明 `AskUserQuestion` 的地方在 `references/voice.md`，而 voice.md 的读取时机写的是"陛下 reply 前"——**开场那一刻陛下尚未 reply**，加上 SKILL.md 注明第一步"不用额外读"，于是严格照主文件执行恰好在最需要机制时读不到机制。**次因**：`opening`/`picks` 命令在 JSON 之外还打印一段编号文字，看着就像可直接粘出去的话术，而 JSON 里 `question`/`multiSelect`/`options` 与提问工具入参同构却无人点明。**其三**：`opening` 与 `picks --stage opening` 两个入口职责重叠、关系未定义 | **机制跟着数据走**：①引擎所有 `picks`（含 `opening`）返回新增 `render_via`／`render_note`／`fallback_note`，写明"填进 AskUserQuestion"；②SKILL.md 第一步新增「呈卡片的执行方式」三步 + "最易犯的错"警告，铁律 7 直接写出工具名；③voice.md 读取时机补上"呈任何选项卡片前（含开场第一步）"，并新增两个入口的对照表；④CLI 编号文字前加横幅标明是**降级兜底**、非话术（测试 165–171 锁定） |
| **开场一项一项追问，效率太低** | 陛下反馈："用户唤起 skill 后，目前只会一个个问题去问，这样效率太低了。" | 原先七步各自为政：先问"今日想用何膳"，陛下点了**再**问用膳方式，**再**问预算，**再**问地址——四轮才凑齐开拟条件，每轮都要等陛下 | **改为三问一卡**：新增 `people_budget`（用度与人数，预设档位全可点）与 `delivery_plan`（外送/自取 + 地址，两条岔路合成一问）两个阶段；`render_opening_bundle()` 把三问打成 `questions` 数组，`opening` 命令默认输出三问包，整组填进 `AskUserQuestion` 一次呈完；宿主不支持多问卡片时 `--single` 降级。SKILL.md 第一步同步改写，并保留 🛑"呈上三问后本轮到此为止"（测试 172–178 锁定） |
| 想靠 IP 自动找最近门店 | 陛下问："agent 能不能根据 IP 自行判断最近门店？" | 臣拿不到 IP（对话无此字段）；但**真正原因是没人看官方返回里就有 `distance`**——服务端按 keyword 地理编码算距离并排好序，与陛下位置无关；`longitude`/`latitude` 恒为 0.0 | **明确不做 IP 定位**（也用不上）。改为：①用陛下已有外送地址反推 city+keyword，返回 `need_confirm` 让陛下**点一下**确认；②新增 `adapt_mcd_nearby_stores()` / `render_store_list()` 展示官方距离与完整 storeCode；③指引"就近不准就换更具体的 keyword"——实测同一查询点下，keyword 从「西湖区」换成「黄龙体育中心」，最近距离由 2545m 降到 188m（测试 136–150 锁定） |
| **打包前自查：文档里夹着陛下真实住址** | 为换机迁移做发布前扫描时发现：README / MCP_INTEGRATION / workflow/03 / 引擎注释 / 测试输入里，把陛下真实收货地址（含 `×幢×室` 单元级）当成"就近寻店"的演示关键词 | 早期为了证明"街道门牌比区县准"，直接拿陛下自己的地址实跑，截图式写进了文档；`.gitignore` 那时也还没排除 `.workbuddy/` | ①全部换成**公开门牌** `天目山路148号`（浙大玉泉校区正门）作示例，距离数字改为 2026-10-23 同点实跑（区县 2545m / 地标 188m / 门牌 410m，三个 traceId 齐全，可复跑）；②新增测试 178 `test_60_publishable_files_must_not_carry_unit_level_address`，按**模式**（`×幢×室` 且无商业标记）守卫——测试文件本身不含真实地址，已用 7 组样例验证不误伤商户铺位；③`.gitignore` 补 `.workbuddy/` |

---

## 三、真实 MCP 调用验证

| 工具 | 结果 | 留痕 |
|---|---|---|
| `query-nearby-stores` | ✅ 返回杭州 5 家门店 | `MCP_INTEGRATION.md` |
| `query-meals` | ✅ 15 分类 / 120+ 餐品 | `tests/fixtures/menu_real_sample.json` |
| `query-store-coupons` | ✅ 成功但返回空列表 | 文档记录 |
| `query-my-coupons` | ✅ 成功但返回空 | 文档记录 |
| `calculate-price` | ✅ 4100 分 = 41.00 元 | `tests/fixtures/price_real_sample.json` |
| `campaign-calendar` | ✅ 当日多条真实活动 | `tests/fixtures/campaign_real_sample.json` |
| `delivery-query-addresses` | ✅ 成功（先空列表，后取到 addressId） | `delivery_addresses_real.json` / `delivery_addresses_filled_real.json` |
| `delivery-query-stores`（beType=2） | ✅ 3 家门店 + `beCode` | `tests/fixtures/delivery_stores_real.json` |
| `query-meals`（beType=2 + beCode） | ✅ 外送菜单（价格高于到店） | `tests/fixtures/delivery_menu_real.json` |
| `calculate-price`（beType=2 + beCode） | ✅ 配送费 6.00 / 打包费 1.90 | `tests/fixtures/delivery_price_real.json` |
| `available-coupons` | ✅ 3 张可领取券 | `tests/fixtures/available_coupons_real.txt` |
| `query-meals`（beType=2，**首次尝试未带 beCode**） | ❌ 被拒 `600048`「必传 beCode」 | `tests/fixtures/delivery_beCode_required_real.json` |
| `delivery-query-stores`（**首次尝试无配送地址**） | ❌ 被拒 `400`「addressId地址ID不能为空」 | `tests/fixtures/delivery_stores_address_required_real.json` |

> 上两行是**首次尝试**的真实报错留痕（当时账户无配送地址）。它们反向确证了两条硬约束，
> 引擎据此在链路未打通时阻塞而非编造；补齐地址后已全部实跑成功（见上方 101–105 行）。

---

## 四、未验证 / 受限制项

| 项 | 状态 | 说明 |
|---|---|---|
| 有券时的**本单**优惠筛选与核价 | ✅ **已验证**（2026-10-22） | 代领券后 `query-store-coupons` **首次返回非空**（2 张），并已用两次官方核价验证券效，见下方专节 |
| 麦乐送外送完整链路（beType=2） | ✅ **已验证** | 2026-10-22 端到端实跑全通：地址 → `beCode` → 外送菜单 → 外送核价（含真实配送费 6.00 / 打包费 1.90） |
| 可领取券令（`available-coupons`） | ✅ **已验证** | 真实返回 3 张券，解析与展示均已测；但属"可领取"非"本单可用"，臣不代领 |
| 跨会话偏好持久化 | ✅ **已实现并验证** | 存档于 `~/.workbuddy/user_data/`，工作区之外；含损坏降级与清除测试 |
| 外送起送价 | ✅ **已澄清** | 麦乐送外送**不设起送门槛**（陛下明示；官方返回中亦无该字段）。原「未能核实」口径已改正，现只作说明、不给金额（测试 44b 锁定） |
| 餐品图片（`query-meal-detail`） | ✅ **已验证** | 2026-10-22 实跑：单品与套餐均返回 `data.image`（官方 CDN）。**并已确认 `query-meals` 菜单列表不返回图片**（测试 60 锁定） |
| 饮品的「必选口味」 | ✅ **已验证**（2026-10-22） | 实跑 `query-meal-detail`（可口可乐中杯 `903050`）：官方 `modification` 只有**冰量四项**（标准／去冰／多冰／少冰），`minValues=1` 表示**必须选一项**，默认「标准」 ⇒ **不问就默认加冰** |
| 「无糖」这件事 | ✅ **已澄清**（2026-10-22） | 同一杯可乐的官方数据里**没有无糖选项**；「无糖可口可乐」是**另一个独立商品**（编码 `903071`，11 元）。 ⇒ 陛下若要无糖，是**换商品**，不是改选项，臣不得假装能改 |
| 团餐（beType=6） | ⚠️ **未验证** | 未实跑，且需预算/人数，本版未实现 |
| 得来速（beType=5） | ⚠️ **未验证** | 未实跑，本版未实现 |
| `query-meal-detail` 全部字段（rounds/modification） | ✅ **已验证** | 2026-10-22 实跑单品 + 套餐，解析默认搭配与特调统计（测试 61/62/67） |
| 代领券令的实际执行（`auto-bind-coupons`） | ✅ **已实跑**（2026-10-22） | 陛下明示「领」后执行，回报成功 3 张；回查卡包实得 2 张，差异已如实对账（测试 81） |
| 领券是否消耗领取资格/次数 | ⚠️ **未核实** | 官方工具声明中未提及，已在输出中如实标注，不装作确定 |
| 代下单的实际执行（`create-order`） | ⚠️ **未实跑** | 三重复述编排已完成并测试（87–95），但**尚未用真实门店 + 真实地址创建过订单**——那会真花钱的边界上，臣不拿陛下的账号做实验。编排就绪后是否出单，由陛下明示 |
| 待支付订单的超时自动取消时长 | ⚠️ **未核实** | 官方声明未给出时限，臣不敢承诺"多久会自动取消" |
| 商品 `1440` 不带券时核不出价的原因 | ⚠️ **未核实** | 已用 `901100` 对照实验排除接口故障，但官方未说明原因，臣**不作断言**（测试 79） |
| 2025 / 2027 法定节假日 | ❌ **未内置** | 只有 2026 年数据已核实；其他年份运行时降级，不编造 |

> 以上均**未**写成"通过"。
