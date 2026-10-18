"""One toolkit-independent keyboard registry for dispatch and the native guide."""

from dataclasses import dataclass
import re


def N_(text):
    """Mark a source label for gettext without translating it at import time."""
    return text


@dataclass(frozen=True)
class Shortcut:
    action: str
    accelerator: str
    title: str
    group: str
    combinations: tuple[tuple[str, frozenset[str]], ...]
    reader_only: bool = False


def keys(names, *modifiers):
    return tuple((name, frozenset(modifiers)) for name in names.split())


GENERAL = N_("Главное меню")
READING = N_("Чтение")

SHORTCUTS = (
    Shortcut("open", "<Control>o", N_("Открыть книги"), GENERAL,
             keys("o O Cyrillic_shcha Cyrillic_SHCHA", "control")),
    Shortcut("search", "<Control>f", N_("Найти"), GENERAL,
             keys("f F Cyrillic_a Cyrillic_A", "control")),
    Shortcut("preferences", "<Control>comma", N_("Настройки"), GENERAL,
             keys("comma", "control")),
    Shortcut("accessibility", "<Control><Shift>a", N_("Специальные возможности"), GENERAL,
             keys("a A Cyrillic_ef Cyrillic_EF", "control", "shift")),
    Shortcut("library", "<Control>1", N_("Мои книги"), GENERAL, keys("1 KP_1", "control")),
    Shortcut("reader", "<Control>2", N_("Чтение"), GENERAL, keys("2 KP_2", "control")),
    Shortcut("catalogs", "<Control>3", N_("Сетевые библиотеки"), GENERAL, keys("3 KP_3", "control")),
    Shortcut("fullscreen", "F11", N_("Полноэкранный режим"), GENERAL, keys("F11")),
    Shortcut("toolbar", "F10", N_("Показать верхнюю панель"), GENERAL, keys("F10")),
    Shortcut("manual", "F1", N_("Руководство пользователя"), GENERAL, keys("F1")),
    Shortcut("shortcuts", "<Control>question", N_("Горячие клавиши"), GENERAL,
             keys("question", "control") + keys("question slash", "control", "shift")),
    Shortcut("quit", "<Control>q", N_("Закрыть приложение"), GENERAL,
             keys("q Q Cyrillic_shorti Cyrillic_SHORTI", "control")),
    Shortcut("day-night", "<Control><Shift>d", N_("Дневной / ночной режим"), GENERAL,
             keys("d D Cyrillic_ve Cyrillic_VE", "control", "shift")),
    Shortcut("larger", "<Control>plus", N_("Увеличить текст"), READING,
             keys("plus equal KP_Add", "control") + keys("plus equal", "control", "shift"), True),
    Shortcut("smaller", "<Control>minus", N_("Уменьшить текст"), READING,
             keys("minus KP_Subtract", "control"), True),
    Shortcut("reset-size", "<Control>0", N_("Стандартный размер текста"), READING,
             keys("0 KP_0", "control"), True),
    Shortcut("previous", "<Alt>Left", N_("Предыдущая глава"), READING,
             keys("Left", "alt"), True),
    Shortcut("next", "<Alt>Right", N_("Следующая глава"), READING,
             keys("Right", "alt"), True),
    Shortcut("contents", "F9", N_("Оглавление"), READING, keys("F9"), True),
    Shortcut("bookmark", "<Control>b", N_("＋ Закладка"), READING,
             keys("b B Cyrillic_i Cyrillic_I", "control"), True),
    Shortcut("speech", "space", N_("Озвучить"), READING, keys("space"), True),
    Shortcut("stop-speech", "<Control><Shift>s", N_("Стоп"), READING,
             keys("s S Cyrillic_yeru Cyrillic_YERU Ukrainian_i Ukrainian_I", "control", "shift"), True),
)


class BindingError(ValueError):
    """A machine-readable validation failure; the UI localizes ``code``."""

    def __init__(self, code="invalid"):
        self.code = code
        super().__init__(code)


_ACTIONS = {shortcut.action: shortcut for shortcut in SHORTCUTS}
_MODIFIERS = ("control", "shift", "alt")
_GTK_MODIFIERS = {"control": "Control", "shift": "Shift", "alt": "Alt"}
_KEY_NAME = re.compile(r"(?:[A-Za-z_][A-Za-z_0-9]{0,63}|[0-9])\Z")
_FUNCTION_KEY = re.compile(r"F(?:[1-9]|[12][0-9]|3[0-5])\Z")
_RESERVED_KEYS = frozenset({
    "Escape", "Tab", "KP_Tab", "ISO_Left_Tab", "ISO_Enter", "NoSymbol", "VoidSymbol",
    "Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R",
    "Super_L", "Super_R", "Meta_L", "Meta_R", "Hyper_L", "Hyper_R",
    "Caps_Lock", "Num_Lock", "Scroll_Lock", "Shift_Lock", "Mode_switch",
    "ISO_Level3_Shift", "ISO_Level5_Shift", "Multi_key", "Menu", "Sys_Req", "Print", "Pause",
})
_PHYSICAL_KEYS = {
    "q": "Cyrillic_shorti", "w": "Cyrillic_tse", "e": "Cyrillic_u",
    "r": "Cyrillic_ka", "t": "Cyrillic_ie", "y": "Cyrillic_en",
    "u": "Cyrillic_ghe", "i": "Cyrillic_sha", "o": "Cyrillic_shcha",
    "p": "Cyrillic_ze", "bracketleft": "Cyrillic_ha", "bracketright": "Cyrillic_hardsign",
    "a": "Cyrillic_ef", "s": "Cyrillic_yeru", "d": "Cyrillic_ve", "f": "Cyrillic_a",
    "g": "Cyrillic_pe", "h": "Cyrillic_er", "j": "Cyrillic_o", "k": "Cyrillic_el",
    "l": "Cyrillic_de", "semicolon": "Cyrillic_zhe", "apostrophe": "Cyrillic_e",
    "z": "Cyrillic_ya", "x": "Cyrillic_che", "c": "Cyrillic_es", "v": "Cyrillic_em",
    "b": "Cyrillic_i", "n": "Cyrillic_te", "m": "Cyrillic_softsign",
    "comma": "Cyrillic_be", "period": "Cyrillic_yu", "grave": "Cyrillic_io",
}
_ALIASES: dict[str, tuple[str, ...]] = {}
_CANONICAL: dict[str, str] = {}
for _latin, _cyrillic in _PHYSICAL_KEYS.items():
    _upper = _cyrillic.split("_", 1)[0] + "_" + _cyrillic.split("_", 1)[1].upper()
    _names = [_latin, _latin.upper() if len(_latin) == 1 else _latin, _cyrillic, _upper]
    if _latin == "s":
        _names.extend(("Ukrainian_i", "Ukrainian_I"))
    _ALIASES[_latin] = tuple(dict.fromkeys(_names))
    for _name in _names:
        _CANONICAL[_name.casefold()] = _latin
for _digit in "0123456789":
    _ALIASES[_digit] = (_digit, "KP_" + _digit)
    _CANONICAL[("KP_" + _digit).casefold()] = _digit
for _key, _alias in (("plus", "KP_Add"), ("minus", "KP_Subtract"), ("Return", "KP_Enter")):
    _ALIASES[_key] = (_key, _alias)
    _CANONICAL[_alias.casefold()] = _key
del _latin, _cyrillic, _upper, _names, _name, _digit, _key, _alias


# Finite symbolic-name data from the standard X11/GDK key namespace. These
# names are factual identifiers, not copied header implementation. Keeping a
# static catalog makes corrupt profiles safe without importing GI/native code.
# Raw U/U+ codepoint spellings are excluded: they do not round-trip through
# Gtk.ShortcutLabel's accelerator parser on all supported GTK versions.
_KNOWN_KEYS = frozenset("""
0 1 2 3 3270_AltCursor 3270_Attn 3270_BackTab 3270_ChangeScreen 3270_Copy 3270_CursorBlink 3270_CursorSelect
3270_DeleteWord 3270_Duplicate 3270_Enter 3270_EraseEOF 3270_EraseInput 3270_ExSelect 3270_FieldMark 3270_Ident
3270_Jump 3270_KeyClick 3270_Left2 3270_PA1 3270_PA2 3270_PA3 3270_Play 3270_PrintScreen 3270_Quit 3270_Record
3270_Reset 3270_Right2 3270_Rule 3270_Setup 3270_Test 4 5 6 7 8 9 A AE Aacute Abreve AccessX_Enable
AccessX_Feedback_Enable Acircumflex AddFavorite Adiaeresis Agrave Alt_L Alt_R Amacron Aogonek ApplicationLeft
ApplicationRight Arabic_0 Arabic_1 Arabic_2 Arabic_3 Arabic_4 Arabic_5 Arabic_6 Arabic_7 Arabic_8 Arabic_9
Arabic_ain Arabic_alef Arabic_alefmaksura Arabic_beh Arabic_comma Arabic_dad Arabic_dal Arabic_damma
Arabic_dammatan Arabic_ddal Arabic_farsi_yeh Arabic_fatha Arabic_fathatan Arabic_feh Arabic_fullstop Arabic_gaf
Arabic_ghain Arabic_ha Arabic_hah Arabic_hamza Arabic_hamza_above Arabic_hamza_below Arabic_hamzaonalef
Arabic_hamzaonwaw Arabic_hamzaonyeh Arabic_hamzaunderalef Arabic_heh Arabic_heh_doachashmee Arabic_heh_goal
Arabic_jeem Arabic_jeh Arabic_kaf Arabic_kasra Arabic_kasratan Arabic_keheh Arabic_khah Arabic_lam
Arabic_madda_above Arabic_maddaonalef Arabic_meem Arabic_noon Arabic_noon_ghunna Arabic_peh Arabic_percent
Arabic_qaf Arabic_question_mark Arabic_ra Arabic_rreh Arabic_sad Arabic_seen Arabic_semicolon Arabic_shadda
Arabic_sheen Arabic_sukun Arabic_superscript_alef Arabic_switch Arabic_tah Arabic_tatweel Arabic_tcheh
Arabic_teh Arabic_tehmarbuta Arabic_thal Arabic_theh Arabic_tteh Arabic_veh Arabic_waw Arabic_yeh
Arabic_yeh_baree Arabic_zah Arabic_zain Aring Armenian_AT Armenian_AYB Armenian_BEN Armenian_CHA Armenian_DA
Armenian_DZA Armenian_E Armenian_FE Armenian_GHAT Armenian_GIM Armenian_HI Armenian_HO Armenian_INI Armenian_JE
Armenian_KE Armenian_KEN Armenian_KHE Armenian_LYUN Armenian_MEN Armenian_NU Armenian_O Armenian_PE
Armenian_PYUR Armenian_RA Armenian_RE Armenian_SE Armenian_SHA Armenian_TCHE Armenian_TO Armenian_TSA
Armenian_TSO Armenian_TYUN Armenian_VEV Armenian_VO Armenian_VYUN Armenian_YECH Armenian_ZA Armenian_ZHE
Armenian_accent Armenian_apostrophe Armenian_at Armenian_ayb Armenian_ben Armenian_cha Armenian_da Armenian_dza
Armenian_e Armenian_exclam Armenian_fe Armenian_full_stop Armenian_ghat Armenian_gim Armenian_hi Armenian_ho
Armenian_hyphen Armenian_ini Armenian_je Armenian_ke Armenian_ken Armenian_khe Armenian_ligature_ew
Armenian_lyun Armenian_men Armenian_nu Armenian_o Armenian_pe Armenian_pyur Armenian_question Armenian_ra
Armenian_re Armenian_se Armenian_separation_mark Armenian_sha Armenian_tche Armenian_to Armenian_tsa
Armenian_tso Armenian_tyun Armenian_vev Armenian_vo Armenian_vyun Armenian_yech Armenian_za Armenian_zhe Atilde
AudibleBell_Enable AudioCycleTrack AudioForward AudioLowerVolume AudioMedia AudioMicMute AudioMute AudioNext
AudioPause AudioPlay AudioPrev AudioRaiseVolume AudioRandomPlay AudioRecord AudioRepeat AudioRewind AudioStop
Away B Babovedot Back BackForward BackSpace Battery Begin Blue Bluetooth Book BounceKeys_Enable Break
BrightnessAdjust Byelorussian_SHORTU Byelorussian_shortu C CD CH C_H C_h Cabovedot Cacute Calculator Calendar
Cancel Caps_Lock Ccaron Ccedilla Ccircumflex Ch Clear Close Codeinput Community ContrastAdjust Control_L
Control_R Copy Cut CycleAngle Cyrillic_A Cyrillic_BE Cyrillic_CHE Cyrillic_CHE_descender Cyrillic_CHE_vertstroke
Cyrillic_DE Cyrillic_DZHE Cyrillic_E Cyrillic_EF Cyrillic_EL Cyrillic_EM Cyrillic_EN Cyrillic_EN_descender
Cyrillic_ER Cyrillic_ES Cyrillic_GHE Cyrillic_GHE_bar Cyrillic_HA Cyrillic_HARDSIGN Cyrillic_HA_descender
Cyrillic_I Cyrillic_IE Cyrillic_IO Cyrillic_I_macron Cyrillic_JE Cyrillic_KA Cyrillic_KA_descender
Cyrillic_KA_vertstroke Cyrillic_LJE Cyrillic_NJE Cyrillic_O Cyrillic_O_bar Cyrillic_PE Cyrillic_SCHWA
Cyrillic_SHA Cyrillic_SHCHA Cyrillic_SHHA Cyrillic_SHORTI Cyrillic_SOFTSIGN Cyrillic_TE Cyrillic_TSE Cyrillic_U
Cyrillic_U_macron Cyrillic_U_straight Cyrillic_U_straight_bar Cyrillic_VE Cyrillic_YA Cyrillic_YERU Cyrillic_YU
Cyrillic_ZE Cyrillic_ZHE Cyrillic_ZHE_descender Cyrillic_a Cyrillic_be Cyrillic_che Cyrillic_che_descender
Cyrillic_che_vertstroke Cyrillic_de Cyrillic_dzhe Cyrillic_e Cyrillic_ef Cyrillic_el Cyrillic_em Cyrillic_en
Cyrillic_en_descender Cyrillic_er Cyrillic_es Cyrillic_ghe Cyrillic_ghe_bar Cyrillic_ha Cyrillic_ha_descender
Cyrillic_hardsign Cyrillic_i Cyrillic_i_macron Cyrillic_ie Cyrillic_io Cyrillic_je Cyrillic_ka
Cyrillic_ka_descender Cyrillic_ka_vertstroke Cyrillic_lje Cyrillic_nje Cyrillic_o Cyrillic_o_bar Cyrillic_pe
Cyrillic_schwa Cyrillic_sha Cyrillic_shcha Cyrillic_shha Cyrillic_shorti Cyrillic_softsign Cyrillic_te
Cyrillic_tse Cyrillic_u Cyrillic_u_macron Cyrillic_u_straight Cyrillic_u_straight_bar Cyrillic_ve Cyrillic_ya
Cyrillic_yeru Cyrillic_yu Cyrillic_ze Cyrillic_zhe Cyrillic_zhe_descender D DOS Dabovedot Dcaron Delete Display
Documents DongSign Down Dstroke E ENG ETH EZH Eabovedot Eacute Ecaron Ecircumflex Ediaeresis Egrave Eisu_Shift
Eisu_toggle Eject Emacron End Eogonek Escape Eth EuroSign Excel Execute Explorer F F1 F10 F11 F12 F13 F14 F15
F16 F17 F18 F19 F2 F20 F21 F22 F23 F24 F25 F26 F27 F28 F29 F3 F30 F31 F32 F33 F34 F35 F4 F5 F6 F7 F8 F9
Fabovedot Farsi_0 Farsi_1 Farsi_2 Farsi_3 Farsi_4 Farsi_5 Farsi_6 Farsi_7 Farsi_8 Farsi_9 Farsi_yeh Favorites
Finance Find First_Virtual_Screen Forward FrameBack FrameForward G Gabovedot Game Gbreve Gcaron Gcedilla
Gcircumflex Georgian_an Georgian_ban Georgian_can Georgian_char Georgian_chin Georgian_cil Georgian_don
Georgian_en Georgian_fi Georgian_gan Georgian_ghan Georgian_hae Georgian_har Georgian_he Georgian_hie
Georgian_hoe Georgian_in Georgian_jhan Georgian_jil Georgian_kan Georgian_khar Georgian_las Georgian_man
Georgian_nar Georgian_on Georgian_par Georgian_phar Georgian_qar Georgian_rae Georgian_san Georgian_shin
Georgian_tan Georgian_tar Georgian_un Georgian_vin Georgian_we Georgian_xan Georgian_zen Georgian_zhar Go
Greek_ALPHA Greek_ALPHAaccent Greek_BETA Greek_CHI Greek_DELTA Greek_EPSILON Greek_EPSILONaccent Greek_ETA
Greek_ETAaccent Greek_GAMMA Greek_IOTA Greek_IOTAaccent Greek_IOTAdiaeresis Greek_KAPPA Greek_LAMBDA Greek_LAMDA
Greek_MU Greek_NU Greek_OMEGA Greek_OMEGAaccent Greek_OMICRON Greek_OMICRONaccent Greek_PHI Greek_PI Greek_PSI
Greek_RHO Greek_SIGMA Greek_TAU Greek_THETA Greek_UPSILON Greek_UPSILONaccent Greek_UPSILONdieresis Greek_XI
Greek_ZETA Greek_accentdieresis Greek_alpha Greek_alphaaccent Greek_beta Greek_chi Greek_delta Greek_epsilon
Greek_epsilonaccent Greek_eta Greek_etaaccent Greek_finalsmallsigma Greek_gamma Greek_horizbar Greek_iota
Greek_iotaaccent Greek_iotaaccentdieresis Greek_iotadieresis Greek_kappa Greek_lambda Greek_lamda Greek_mu
Greek_nu Greek_omega Greek_omegaaccent Greek_omicron Greek_omicronaccent Greek_phi Greek_pi Greek_psi Greek_rho
Greek_sigma Greek_tau Greek_theta Greek_upsilon Greek_upsilonaccent Greek_upsilonaccentdieresis
Greek_upsilondieresis Greek_xi Greek_zeta Green H Hangul Hangul_A Hangul_AE Hangul_AraeA Hangul_AraeAE
Hangul_Banja Hangul_Cieuc Hangul_Dikeud Hangul_E Hangul_EO Hangul_EU Hangul_End Hangul_Hanja Hangul_Hieuh
Hangul_I Hangul_Ieung Hangul_J_Cieuc Hangul_J_Dikeud Hangul_J_Hieuh Hangul_J_Ieung Hangul_J_Jieuj
Hangul_J_Khieuq Hangul_J_Kiyeog Hangul_J_KiyeogSios Hangul_J_KkogjiDalrinIeung Hangul_J_Mieum Hangul_J_Nieun
Hangul_J_NieunHieuh Hangul_J_NieunJieuj Hangul_J_PanSios Hangul_J_Phieuf Hangul_J_Pieub Hangul_J_PieubSios
Hangul_J_Rieul Hangul_J_RieulHieuh Hangul_J_RieulKiyeog Hangul_J_RieulMieum Hangul_J_RieulPhieuf
Hangul_J_RieulPieub Hangul_J_RieulSios Hangul_J_RieulTieut Hangul_J_Sios Hangul_J_SsangKiyeog Hangul_J_SsangSios
Hangul_J_Tieut Hangul_J_YeorinHieuh Hangul_Jamo Hangul_Jeonja Hangul_Jieuj Hangul_Khieuq Hangul_Kiyeog
Hangul_KiyeogSios Hangul_KkogjiDalrinIeung Hangul_Mieum Hangul_MultipleCandidate Hangul_Nieun Hangul_NieunHieuh
Hangul_NieunJieuj Hangul_O Hangul_OE Hangul_PanSios Hangul_Phieuf Hangul_Pieub Hangul_PieubSios Hangul_PostHanja
Hangul_PreHanja Hangul_PreviousCandidate Hangul_Rieul Hangul_RieulHieuh Hangul_RieulKiyeog Hangul_RieulMieum
Hangul_RieulPhieuf Hangul_RieulPieub Hangul_RieulSios Hangul_RieulTieut Hangul_RieulYeorinHieuh Hangul_Romaja
Hangul_SingleCandidate Hangul_Sios Hangul_Special Hangul_SsangDikeud Hangul_SsangJieuj Hangul_SsangKiyeog
Hangul_SsangPieub Hangul_SsangSios Hangul_Start Hangul_SunkyeongeumMieum Hangul_SunkyeongeumPhieuf
Hangul_SunkyeongeumPieub Hangul_Tieut Hangul_U Hangul_WA Hangul_WAE Hangul_WE Hangul_WEO Hangul_WI Hangul_YA
Hangul_YAE Hangul_YE Hangul_YEO Hangul_YI Hangul_YO Hangul_YU Hangul_YeorinHieuh Hankaku Hcircumflex Help Henkan
Henkan_Mode Hibernate Hiragana Hiragana_Katakana History Home HomePage HotLinks Hstroke Hyper_L Hyper_R I
ISO_Center_Object ISO_Continuous_Underline ISO_Discontinuous_Underline ISO_Emphasize ISO_Enter
ISO_Fast_Cursor_Down ISO_Fast_Cursor_Left ISO_Fast_Cursor_Right ISO_Fast_Cursor_Up ISO_First_Group
ISO_First_Group_Lock ISO_Group_Latch ISO_Group_Lock ISO_Last_Group ISO_Last_Group_Lock ISO_Left_Tab
ISO_Level2_Latch ISO_Level3_Latch ISO_Level3_Lock ISO_Level3_Shift ISO_Level5_Latch ISO_Level5_Lock
ISO_Level5_Shift ISO_Lock ISO_Move_Line_Down ISO_Move_Line_Up ISO_Next_Group ISO_Next_Group_Lock
ISO_Partial_Line_Down ISO_Partial_Line_Up ISO_Partial_Space_Left ISO_Partial_Space_Right ISO_Prev_Group
ISO_Prev_Group_Lock ISO_Release_Both_Margins ISO_Release_Margin_Left ISO_Release_Margin_Right
ISO_Set_Margin_Left ISO_Set_Margin_Right Iabovedot Iacute Ibreve Icircumflex Idiaeresis Igrave Imacron Insert
Iogonek Itilde J Jcircumflex K KP_0 KP_1 KP_2 KP_3 KP_4 KP_5 KP_6 KP_7 KP_8 KP_9 KP_Add KP_Begin KP_Decimal
KP_Delete KP_Divide KP_Down KP_End KP_Enter KP_Equal KP_F1 KP_F2 KP_F3 KP_F4 KP_Home KP_Insert KP_Left
KP_Multiply KP_Next KP_Page_Up KP_Prior KP_Right KP_Separator KP_Space KP_Subtract KP_Tab KP_Up Kana_Lock
Kana_Shift Kanji Katakana KbdBrightnessDown KbdBrightnessUp KbdLightOnOff Kcedilla Korean_Won L L1 L10 L2 L3 L4
L5 L6 L7 L8 L9 Lacute Last_Virtual_Screen Launch0 Launch1 Launch2 Launch3 Launch4 Launch5 Launch6 Launch7
Launch8 Launch9 LaunchA LaunchB LaunchC LaunchD LaunchE LaunchF Lcaron Lcedilla Left LightBulb Linefeed LogOff
Lstroke M Mabovedot Macedonia_DSE Macedonia_GJE Macedonia_KJE Macedonia_dse Macedonia_gje Macedonia_kje Mail
MailForward Market Massyo Meeting Memo Menu MenuKB MenuPB Messenger Meta_L Meta_R ModeLock Mode_switch
MonBrightnessDown MonBrightnessUp MouseKeys_Accel_Enable MouseKeys_Enable Muhenkan Multi_key Music MyComputer
MySites N Nacute Ncaron Ncedilla New NewSheqelSign News Next Next_Virtual_Screen NoSymbol Ntilde Num_Lock O OE
Oacute Ocircumflex Odiaeresis Odoubleacute OfficeHome Ograve Ohorn Omacron Ooblique Open OpenURL Option Oslash
Otilde Overlay1_Enable Overlay2_Enable P Pabovedot Page_Down Page_Up Paste Pause Phone Pictures
Pointer_Accelerate Pointer_Button1 Pointer_Button2 Pointer_Button3 Pointer_Button4 Pointer_Button5
Pointer_Button_Dflt Pointer_DblClick1 Pointer_DblClick2 Pointer_DblClick3 Pointer_DblClick4 Pointer_DblClick5
Pointer_DblClick_Dflt Pointer_DfltBtnNext Pointer_DfltBtnPrev Pointer_Down Pointer_DownLeft Pointer_DownRight
Pointer_Drag1 Pointer_Drag2 Pointer_Drag3 Pointer_Drag4 Pointer_Drag5 Pointer_Drag_Dflt Pointer_EnableKeys
Pointer_Left Pointer_Right Pointer_Up Pointer_UpLeft Pointer_UpRight PowerDown PowerOff Prev_Virtual_Screen
Print Prior Q R R5 Racute Rcaron Rcedilla Red Redo Refresh Reload RepeatKeys_Enable Reply Return Right
RockerDown RockerEnter RockerUp Romaji RotateWindows RotationKB RotationPB RupeeSign S SCHWA Sabovedot Sacute
Save Scaron Scedilla Scircumflex ScreenSaver ScrollClick ScrollDown ScrollUp Scroll_Lock Search Select
SelectButton Send Serbian_DJE Serbian_TSHE Serbian_dje Serbian_tshe Shift_L Shift_Lock Shift_R Shop Sinh_a
Sinh_aa Sinh_aa2 Sinh_ae Sinh_ae2 Sinh_aee Sinh_aee2 Sinh_ai Sinh_ai2 Sinh_al Sinh_au Sinh_au2 Sinh_ba Sinh_bha
Sinh_ca Sinh_cha Sinh_dda Sinh_ddha Sinh_dha Sinh_dhha Sinh_e Sinh_e2 Sinh_ee Sinh_ee2 Sinh_fa Sinh_ga Sinh_gha
Sinh_h2 Sinh_ha Sinh_i Sinh_i2 Sinh_ii Sinh_ii2 Sinh_ja Sinh_jha Sinh_jnya Sinh_ka Sinh_kha Sinh_kunddaliya
Sinh_la Sinh_lla Sinh_lu Sinh_lu2 Sinh_luu Sinh_luu2 Sinh_ma Sinh_mba Sinh_na Sinh_ndda Sinh_ndha Sinh_ng
Sinh_ng2 Sinh_nga Sinh_nja Sinh_nna Sinh_nya Sinh_o Sinh_o2 Sinh_oo Sinh_oo2 Sinh_pa Sinh_pha Sinh_ra Sinh_ri
Sinh_rii Sinh_ru2 Sinh_ruu2 Sinh_sa Sinh_sha Sinh_ssha Sinh_tha Sinh_thha Sinh_tta Sinh_ttha Sinh_u Sinh_u2
Sinh_uu Sinh_uu2 Sinh_va Sinh_ya Sleep SlowKeys_Enable Spell SplitScreen Standby Start StickyKeys_Enable Stop
Subtitle Super_L Super_R Support Suspend Sys_Req T THORN Tab Tabovedot TaskPane Tcaron Tcedilla Terminal
Terminate_Server Thai_baht Thai_bobaimai Thai_chochan Thai_chochang Thai_choching Thai_chochoe Thai_dochada
Thai_dodek Thai_fofa Thai_fofan Thai_hohip Thai_honokhuk Thai_khokhai Thai_khokhon Thai_khokhuat Thai_khokhwai
Thai_khorakhang Thai_kokai Thai_lakkhangyao Thai_lekchet Thai_lekha Thai_lekhok Thai_lekkao Thai_leknung
Thai_lekpaet Thai_leksam Thai_leksi Thai_leksong Thai_leksun Thai_lochula Thai_loling Thai_lu Thai_maichattawa
Thai_maiek Thai_maihanakat Thai_maihanakat_maitho Thai_maitaikhu Thai_maitho Thai_maitri Thai_maiyamok Thai_moma
Thai_ngongu Thai_nikhahit Thai_nonen Thai_nonu Thai_oang Thai_paiyannoi Thai_phinthu Thai_phophan Thai_phophung
Thai_phosamphao Thai_popla Thai_rorua Thai_ru Thai_saraa Thai_saraaa Thai_saraae Thai_saraaimaimalai
Thai_saraaimaimuan Thai_saraam Thai_sarae Thai_sarai Thai_saraii Thai_sarao Thai_sarau Thai_saraue Thai_sarauee
Thai_sarauu Thai_sorusi Thai_sosala Thai_soso Thai_sosua Thai_thanthakhat Thai_thonangmontho Thai_thophuthao
Thai_thothahan Thai_thothan Thai_thothong Thai_thothung Thai_topatak Thai_totao Thai_wowaen Thai_yoyak
Thai_yoying Thorn Time ToDoList Tools TopMenu TouchpadOff TouchpadOn TouchpadToggle Touroku Travel Tslash U UWB
Uacute Ubreve Ucircumflex Udiaeresis Udoubleacute Ugrave Uhorn Ukrainian_GHE_WITH_UPTURN Ukrainian_I
Ukrainian_IE Ukrainian_YI Ukrainian_ghe_with_upturn Ukrainian_i Ukrainian_ie Ukrainian_yi Umacron Undo Ungrab
Uogonek Up Uring User1KB User2KB UserPB Utilde V VendorHome Video View VoidSymbol W WLAN WWW Wacute WakeUp
WebCam WheelButton WindowClear Word X XF86AddFavorite XF86ApplicationLeft XF86ApplicationRight XF86AudioForward
XF86AudioLowerVolume XF86AudioMedia XF86AudioMicMute XF86AudioMute XF86AudioNext XF86AudioPause XF86AudioPlay
XF86AudioPrev XF86AudioRaiseVolume XF86AudioRandomPlay XF86AudioRecord XF86AudioRewind XF86AudioStop XF86Away
XF86Back XF86BackForward XF86Battery XF86Bluetooth XF86Book XF86Break XF86BrightnessAdjust XF86CD XF86Calculator
XF86Calendar XF86Clear XF86Close XF86Community XF86ContrastAdjust XF86Copy XF86Cut XF86CycleAngle XF86DOS
XF86Display XF86Documents XF86Eject XF86Excel XF86Explorer XF86Favorites XF86Finance XF86Forward XF86FrameBack
XF86FrameForward XF86Game XF86Go XF86Hibernate XF86History XF86HomePage XF86HotLinks XF86KbdBrightnessDown
XF86KbdBrightnessUp XF86KbdLightOnOff XF86Launch0 XF86Launch1 XF86Launch2 XF86Launch3 XF86Launch4 XF86Launch5
XF86Launch6 XF86Launch7 XF86Launch8 XF86Launch9 XF86LaunchA XF86LaunchB XF86LaunchC XF86LaunchD XF86LaunchE
XF86LaunchF XF86LightBulb XF86LogGrabInfo XF86LogOff XF86LogWindowTree XF86Mail XF86MailForward XF86Market
XF86Meeting XF86MenuKB XF86MenuPB XF86Messenger XF86ModeLock XF86MonBrightnessDown XF86MonBrightnessUp XF86Music
XF86MyComputer XF86New XF86News XF86Next_VMode XF86OfficeHome XF86Open XF86OpenURL XF86Paste XF86Phone
XF86Pictures XF86PowerOff XF86Prev_VMode XF86Q XF86Reload XF86Reply XF86RotateWindows XF86RotationKB
XF86RotationPB XF86Save XF86ScreenSaver XF86ScrollClick XF86ScrollDown XF86ScrollUp XF86Search XF86Send XF86Shop
XF86Sleep XF86Spell XF86SplitScreen XF86Standby XF86Start XF86Stop XF86Support XF86Suspend XF86TaskPane
XF86Terminal XF86ToDoList XF86Tools XF86TouchpadOff XF86TouchpadOn XF86TouchpadToggle XF86Travel XF86UWB
XF86User1KB XF86User2KB XF86UserPB XF86VendorHome XF86Video XF86WLAN XF86WWW XF86WakeUp XF86WebCam XF86Word
XF86Xfer XF86ZoomIn XF86ZoomOut XF86iTouch Xfer Y Yacute Ydiaeresis Yellow Z Zabovedot Zacute Zcaron Zenkaku
Zenkaku_Hankaku ZoomIn ZoomOut a aacute abovedot abreve acircumflex acute adiaeresis ae agrave amacron ampersand
aogonek apostrophe approxeq approximate aring asciicircum asciitilde asterisk at atilde b babovedot backslash
ballotcross bar because blank botintegral botleftparens botleftsqbracket botleftsummation botrightparens
botrightsqbracket botrightsummation bott botvertsummationconnector braceleft braceright bracketleft bracketright
braille_dot_1 braille_dot_10 braille_dot_2 braille_dot_3 braille_dot_4 braille_dot_5 braille_dot_6 braille_dot_7
braille_dot_8 braille_dot_9 breve brokenbar c c_h cabovedot cacute careof caret caron ccaron ccedilla
ccircumflex cedilla cent ch checkerboard checkmark circle club colon comma copyright cr crossinglines currency
cursor d dabovedot dagger dcaron dead_A dead_E dead_I dead_O dead_U dead_a dead_abovecomma dead_abovedot
dead_abovereversedcomma dead_abovering dead_acute dead_belowbreve dead_belowcircumflex dead_belowcomma
dead_belowdiaeresis dead_belowdot dead_belowmacron dead_belowring dead_belowtilde dead_breve dead_capital_schwa
dead_caron dead_cedilla dead_circumflex dead_currency dead_dasia dead_diaeresis dead_doubleacute
dead_doublegrave dead_e dead_grave dead_greek dead_hook dead_horn dead_i dead_invertedbreve dead_iota
dead_macron dead_o dead_ogonek dead_perispomeni dead_psili dead_semivoiced_sound dead_small_schwa dead_stroke
dead_tilde dead_u dead_voiced_sound decimalpoint degree diaeresis diamond digitspace division dollar
doubbaselinedot doubleacute doubledagger doublelowquotemark downarrow downcaret downshoe downstile downtack
dstroke e eabovedot eacute ecaron ecircumflex ediaeresis egrave eightsuperior elementof ellipsis em3space
em4space emacron emdash emfilledcircle emfilledrect emopencircle emopenrectangle emptyset emspace endash
enfilledcircbullet enfilledsqbullet eng enopencircbullet enopensquarebullet enspace eogonek equal eth exclam
exclamdown ezh f fabovedot femalesymbol ff figdash filledlefttribullet filledrectbullet filledrighttribullet
filledtribulletdown filledtribulletup fiveeighths fivesixths fivesuperior fourfifths foursuperior function g
gabovedot gbreve gcaron gcedilla gcircumflex grave greater greaterthanequal guillemotleft guillemotright h
hairspace hcircumflex heart hebrew_aleph hebrew_ayin hebrew_bet hebrew_chet hebrew_dalet hebrew_doublelowline
hebrew_finalkaph hebrew_finalmem hebrew_finalnun hebrew_finalpe hebrew_finalzade hebrew_gimel hebrew_he
hebrew_kaph hebrew_kuf hebrew_lamed hebrew_mem hebrew_nun hebrew_pe hebrew_qoph hebrew_resh hebrew_samech
hebrew_shin hebrew_taf hebrew_taw hebrew_tet hebrew_waw hebrew_yod hebrew_zade hebrew_zain hexagram
horizconnector horizlinescan1 horizlinescan3 horizlinescan5 horizlinescan7 horizlinescan9 hstroke ht hyphen i
iTouch iacute ibreve icircumflex identical idiaeresis idotless ifonlyif igrave imacron implies includedin
includes infinity integral intersection iogonek itilde j jcircumflex jot k kana_A kana_CHI kana_E kana_FU
kana_HA kana_HE kana_HI kana_HO kana_I kana_KA kana_KE kana_KI kana_KO kana_KU kana_MA kana_ME kana_MI kana_MO
kana_MU kana_N kana_NA kana_NE kana_NI kana_NO kana_NU kana_O kana_RA kana_RE kana_RI kana_RO kana_RU kana_SA
kana_SE kana_SHI kana_SO kana_SU kana_TA kana_TE kana_TO kana_TSU kana_U kana_WA kana_WO kana_YA kana_YO kana_YU
kana_a kana_closingbracket kana_comma kana_conjunctive kana_e kana_fullstop kana_i kana_middledot kana_o
kana_openingbracket kana_tsu kana_u kana_ya kana_yo kana_yu kappa kcedilla kra l lacute latincross lcaron
lcedilla leftanglebracket leftarrow leftcaret leftdoublequotemark leftmiddlecurlybrace leftopentriangle
leftpointer leftradical leftshoe leftsinglequotemark leftt lefttack less lessthanequal lf logicaland logicalor
lowleftcorner lowrightcorner lstroke m mabovedot macron malesymbol maltesecross marker masculine minus minutes
mu multiply musicalflat musicalsharp n nabla nacute ncaron ncedilla ninesuperior nl nobreakspace notelementof
notequal notsign ntilde numbersign numerosign o oacute ocircumflex odiaeresis odoubleacute oe ogonek ograve
ohorn omacron oneeighth onefifth onehalf onequarter onesixth onesubscript onesuperior onethird ooblique
openrectbullet openstar opentribulletdown opentribulletup ordfeminine oslash otilde overbar overline p pabovedot
paragraph parenleft parenright partdifferential partialderivative percent period periodcentered permille
phonographcopyright plus plusminus prescription prolongedsound punctspace q quad question questiondown quotedbl
r racute radical rcaron rcedilla registered rightanglebracket rightarrow rightcaret rightdoublequotemark
rightmiddlecurlybrace rightmiddlesummation rightopentriangle rightpointer rightshoe rightsinglequotemark rightt
righttack s sabovedot sacute scaron scedilla schwa scircumflex seconds section semicolon semivoicedsound
seveneighths sevensuperior signaturemark signifblank similarequal singlelowquotemark sixsuperior slash
soliddiamond space squareroot ssharp sterling t tabovedot tcaron tcedilla telephone telephonerecorder therefore
thinspace thorn threeeighths threefifths threequarters threesubscript threesuperior topintegral topleftparens
topleftradical topleftsqbracket topleftsummation toprightparens toprightsqbracket toprightsummation topt
topvertsummationconnector trademark trademarkincircle tslash twofifths twosubscript twosuperior twothirds u
uacute ubreve ucircumflex udiaeresis udoubleacute ugrave uhorn umacron underbar underscore union uogonek uparrow
upcaret upleftcorner uprightcorner upshoe upstile uptack uring utilde v variation vertbar vertconnector
voicedsound vt w wacute x y yacute ydiaeresis yen z zabovedot zacute zcaron zerosubscript zerosuperior
""".split())


# Native aliases are reduced before physical-layout aliases, so e.g. Prior
# and Page_Up cannot become two owners of the same actual key.
_NATIVE_ALIASES = dict(item.split("=", 1) for item in """
Arabic_0=U+0660 Arabic_1=U+0661 Arabic_2=U+0662 Arabic_3=U+0663 Arabic_4=U+0664 Arabic_5=U+0665 Arabic_6=U+0666
Arabic_7=U+0667 Arabic_8=U+0668 Arabic_9=U+0669 Arabic_ddal=U+0688 Arabic_farsi_yeh=U+06CC
Arabic_fullstop=U+06D4 Arabic_gaf=U+06AF Arabic_hamza_above=U+0654 Arabic_hamza_below=U+0655
Arabic_heh=Arabic_ha Arabic_heh_doachashmee=U+06BE Arabic_heh_goal=U+06C1 Arabic_jeh=U+0698 Arabic_keheh=U+06A9
Arabic_madda_above=U+0653 Arabic_noon_ghunna=U+06BA Arabic_peh=U+067E Arabic_percent=U+066A Arabic_rreh=U+0691
Arabic_superscript_alef=U+0670 Arabic_tcheh=U+0686 Arabic_tteh=U+0679 Arabic_veh=U+06A4 Arabic_yeh_baree=U+06D2
Armenian_AT=U+0538 Armenian_AYB=U+0531 Armenian_BEN=U+0532 Armenian_CHA=U+0549 Armenian_DA=U+0534
Armenian_DZA=U+0541 Armenian_E=U+0537 Armenian_FE=U+0556 Armenian_GHAT=U+0542 Armenian_GIM=U+0533
Armenian_HI=U+0545 Armenian_HO=U+0540 Armenian_INI=U+053B Armenian_JE=U+054B Armenian_KE=U+0554
Armenian_KEN=U+053F Armenian_KHE=U+053D Armenian_LYUN=U+053C Armenian_MEN=U+0544 Armenian_NU=U+0546
Armenian_O=U+0555 Armenian_PE=U+054A Armenian_PYUR=U+0553 Armenian_RA=U+054C Armenian_RE=U+0550
Armenian_SE=U+054D Armenian_SHA=U+0547 Armenian_TCHE=U+0543 Armenian_TO=U+0539 Armenian_TSA=U+053E
Armenian_TSO=U+0551 Armenian_TYUN=U+054F Armenian_VEV=U+054E Armenian_VO=U+0548 Armenian_VYUN=U+0552
Armenian_YECH=U+0535 Armenian_ZA=U+0536 Armenian_ZHE=U+053A Armenian_accent=U+055B Armenian_apostrophe=U+055A
Armenian_at=U+0568 Armenian_ayb=U+0561 Armenian_ben=U+0562 Armenian_cha=U+0579 Armenian_da=U+0564
Armenian_dza=U+0571 Armenian_e=U+0567 Armenian_exclam=U+055C Armenian_fe=U+0586 Armenian_full_stop=U+0589
Armenian_ghat=U+0572 Armenian_gim=U+0563 Armenian_hi=U+0575 Armenian_ho=U+0570 Armenian_hyphen=U+058A
Armenian_ini=U+056B Armenian_je=U+057B Armenian_ke=U+0584 Armenian_ken=U+056F Armenian_khe=U+056D
Armenian_ligature_ew=U+0587 Armenian_lyun=U+056C Armenian_men=U+0574 Armenian_nu=U+0576 Armenian_o=U+0585
Armenian_pe=U+057A Armenian_pyur=U+0583 Armenian_question=U+055E Armenian_ra=U+057C Armenian_re=U+0580
Armenian_se=U+057D Armenian_separation_mark=U+055D Armenian_sha=U+0577 Armenian_tche=U+0573 Armenian_to=U+0569
Armenian_tsa=U+056E Armenian_tso=U+0581 Armenian_tyun=U+057F Armenian_vev=U+057E Armenian_vo=U+0578
Armenian_vyun=U+0582 Armenian_yech=U+0565 Armenian_za=U+0566 Armenian_zhe=U+056A Babovedot=U+1E02
Cyrillic_CHE_descender=U+04B6 Cyrillic_CHE_vertstroke=U+04B8 Cyrillic_EN_descender=U+04A2
Cyrillic_GHE_bar=U+0492 Cyrillic_HA_descender=U+04B2 Cyrillic_I_macron=U+04E2 Cyrillic_KA_descender=U+049A
Cyrillic_KA_vertstroke=U+049C Cyrillic_O_bar=U+04E8 Cyrillic_SCHWA=U+04D8 Cyrillic_SHHA=U+04BA
Cyrillic_U_macron=U+04EE Cyrillic_U_straight=U+04AE Cyrillic_U_straight_bar=U+04B0 Cyrillic_ZHE_descender=U+0496
Cyrillic_che_descender=U+04B7 Cyrillic_che_vertstroke=U+04B9 Cyrillic_en_descender=U+04A3
Cyrillic_ghe_bar=U+0493 Cyrillic_ha_descender=U+04B3 Cyrillic_i_macron=U+04E3 Cyrillic_ka_descender=U+049B
Cyrillic_ka_vertstroke=U+049D Cyrillic_o_bar=U+04E9 Cyrillic_schwa=U+04D9 Cyrillic_shha=U+04BB
Cyrillic_u_macron=U+04EF Cyrillic_u_straight=U+04AF Cyrillic_u_straight_bar=U+04B1 Cyrillic_zhe_descender=U+0497
Dabovedot=U+1E0A DongSign=U+20AB ETH=Eth EZH=U+01B7 Fabovedot=U+1E1E Farsi_0=U+06F0 Farsi_1=U+06F1
Farsi_2=U+06F2 Farsi_3=U+06F3 Farsi_4=U+06F4 Farsi_5=U+06F5 Farsi_6=U+06F6 Farsi_7=U+06F7 Farsi_8=U+06F8
Farsi_9=U+06F9 Farsi_yeh=U+06CC Gcaron=U+01E6 Georgian_an=U+10D0 Georgian_ban=U+10D1 Georgian_can=U+10EA
Georgian_char=U+10ED Georgian_chin=U+10E9 Georgian_cil=U+10EC Georgian_don=U+10D3 Georgian_en=U+10D4
Georgian_fi=U+10F6 Georgian_gan=U+10D2 Georgian_ghan=U+10E6 Georgian_hae=U+10F0 Georgian_har=U+10F4
Georgian_he=U+10F1 Georgian_hie=U+10F2 Georgian_hoe=U+10F5 Georgian_in=U+10D8 Georgian_jhan=U+10EF
Georgian_jil=U+10EB Georgian_kan=U+10D9 Georgian_khar=U+10E5 Georgian_las=U+10DA Georgian_man=U+10DB
Georgian_nar=U+10DC Georgian_on=U+10DD Georgian_par=U+10DE Georgian_phar=U+10E4 Georgian_qar=U+10E7
Georgian_rae=U+10E0 Georgian_san=U+10E1 Georgian_shin=U+10E8 Georgian_tan=U+10D7 Georgian_tar=U+10E2
Georgian_un=U+10E3 Georgian_vin=U+10D5 Georgian_we=U+10F3 Georgian_xan=U+10EE Georgian_zen=U+10D6
Georgian_zhar=U+10DF Greek_LAMDA=Greek_LAMBDA Greek_lamda=Greek_lambda Henkan_Mode=Henkan Ibreve=U+012C
KP_Prior=KP_Page_Up L1=F11 L10=F20 L2=F12 L3=F13 L4=F14 L5=F15 L6=F16 L7=F17 L8=F18 L9=F19 Mabovedot=U+1E40
Mode_switch=Arabic_switch NewSheqelSign=U+20AA Next=Page_Down Ohorn=U+01A0 Oslash=Ooblique Pabovedot=U+1E56
Prior=Page_Up R5=F25 RupeeSign=U+20A8 SCHWA=U+018F Sabovedot=U+1E60 Sinh_a=U+0D85 Sinh_aa=U+0D86 Sinh_aa2=U+0DCF
Sinh_ae=U+0D87 Sinh_ae2=U+0DD0 Sinh_aee=U+0D88 Sinh_aee2=U+0DD1 Sinh_ai=U+0D93 Sinh_ai2=U+0DDB Sinh_al=U+0DCA
Sinh_au=U+0D96 Sinh_au2=U+0DDE Sinh_ba=U+0DB6 Sinh_bha=U+0DB7 Sinh_ca=U+0DA0 Sinh_cha=U+0DA1 Sinh_dda=U+0DA9
Sinh_ddha=U+0DAA Sinh_dha=U+0DAF Sinh_dhha=U+0DB0 Sinh_e=U+0D91 Sinh_e2=U+0DD9 Sinh_ee=U+0D92 Sinh_ee2=U+0DDA
Sinh_fa=U+0DC6 Sinh_ga=U+0D9C Sinh_gha=U+0D9D Sinh_h2=U+0D83 Sinh_ha=U+0DC4 Sinh_i=U+0D89 Sinh_i2=U+0DD2
Sinh_ii=U+0D8A Sinh_ii2=U+0DD3 Sinh_ja=U+0DA2 Sinh_jha=U+0DA3 Sinh_jnya=U+0DA5 Sinh_ka=U+0D9A Sinh_kha=U+0D9B
Sinh_kunddaliya=U+0DF4 Sinh_la=U+0DBD Sinh_lla=U+0DC5 Sinh_lu=U+0D8F Sinh_lu2=U+0DDF Sinh_luu=U+0D90
Sinh_luu2=U+0DF3 Sinh_ma=U+0DB8 Sinh_mba=U+0DB9 Sinh_na=U+0DB1 Sinh_ndda=U+0DAC Sinh_ndha=U+0DB3 Sinh_ng=U+0D82
Sinh_ng2=U+0D9E Sinh_nga=U+0D9F Sinh_nja=U+0DA6 Sinh_nna=U+0DAB Sinh_nya=U+0DA4 Sinh_o=U+0D94 Sinh_o2=U+0DDC
Sinh_oo=U+0D95 Sinh_oo2=U+0DDD Sinh_pa=U+0DB4 Sinh_pha=U+0DB5 Sinh_ra=U+0DBB Sinh_ri=U+0D8D Sinh_rii=U+0D8E
Sinh_ru2=U+0DD8 Sinh_ruu2=U+0DF2 Sinh_sa=U+0DC3 Sinh_sha=U+0DC1 Sinh_ssha=U+0DC2 Sinh_tha=U+0DAD
Sinh_thha=U+0DAE Sinh_tta=U+0DA7 Sinh_ttha=U+0DA8 Sinh_u=U+0D8B Sinh_u2=U+0DD4 Sinh_uu=U+0D8C Sinh_uu2=U+0DD6
Sinh_va=U+0DC0 Sinh_ya=U+0DBA THORN=Thorn Tabovedot=U+1E6A Uhorn=U+01AF Wacute=U+1E82
XF86AddFavorite=AddFavorite XF86ApplicationLeft=ApplicationLeft XF86ApplicationRight=ApplicationRight
XF86AudioForward=AudioForward XF86AudioLowerVolume=AudioLowerVolume XF86AudioMedia=AudioMedia
XF86AudioMicMute=AudioMicMute XF86AudioMute=AudioMute XF86AudioNext=AudioNext XF86AudioPause=AudioPause
XF86AudioPlay=AudioPlay XF86AudioPrev=AudioPrev XF86AudioRaiseVolume=AudioRaiseVolume
XF86AudioRandomPlay=AudioRandomPlay XF86AudioRecord=AudioRecord XF86AudioRewind=AudioRewind
XF86AudioStop=AudioStop XF86Away=Away XF86Back=Back XF86BackForward=BackForward XF86Battery=Battery
XF86Bluetooth=Bluetooth XF86Book=Book XF86Break=Break XF86BrightnessAdjust=BrightnessAdjust XF86CD=CD
XF86Calculator=Calculator XF86Calendar=Calendar XF86Clear=Clear XF86Close=Close XF86Community=Community
XF86ContrastAdjust=ContrastAdjust XF86Copy=Copy XF86Cut=Cut XF86CycleAngle=CycleAngle XF86DOS=DOS
XF86Display=Display XF86Documents=Documents XF86Eject=Eject XF86Excel=Excel XF86Explorer=Explorer
XF86Favorites=Favorites XF86Finance=Finance XF86Forward=Forward XF86FrameBack=FrameBack
XF86FrameForward=FrameForward XF86Game=Game XF86Go=Go XF86Hibernate=Hibernate XF86History=History
XF86HomePage=HomePage XF86HotLinks=HotLinks XF86KbdBrightnessDown=KbdBrightnessDown
XF86KbdBrightnessUp=KbdBrightnessUp XF86KbdLightOnOff=KbdLightOnOff XF86Launch0=Launch0 XF86Launch1=Launch1
XF86Launch2=Launch2 XF86Launch3=Launch3 XF86Launch4=Launch4 XF86Launch5=Launch5 XF86Launch6=Launch6
XF86Launch7=Launch7 XF86Launch8=Launch8 XF86Launch9=Launch9 XF86LaunchA=LaunchA XF86LaunchB=LaunchB
XF86LaunchC=LaunchC XF86LaunchD=LaunchD XF86LaunchE=LaunchE XF86LaunchF=LaunchF XF86LightBulb=LightBulb
XF86LogGrabInfo=LogGrabInfo XF86LogOff=LogOff XF86LogWindowTree=LogWindowTree XF86Mail=Mail
XF86MailForward=MailForward XF86Market=Market XF86Meeting=Meeting XF86MenuKB=MenuKB XF86MenuPB=MenuPB
XF86Messenger=Messenger XF86ModeLock=ModeLock XF86MonBrightnessDown=MonBrightnessDown
XF86MonBrightnessUp=MonBrightnessUp XF86Music=Music XF86MyComputer=MyComputer XF86New=New XF86News=News
XF86Next_VMode=Next_VMode XF86OfficeHome=OfficeHome XF86Open=Open XF86OpenURL=OpenURL XF86Paste=Paste
XF86Phone=Phone XF86Pictures=Pictures XF86PowerOff=PowerOff XF86Prev_VMode=Prev_VMode XF86Q=Q XF86Reload=Reload
XF86Reply=Reply XF86RotateWindows=RotateWindows XF86RotationKB=RotationKB XF86RotationPB=RotationPB
XF86Save=Save XF86ScreenSaver=ScreenSaver XF86ScrollClick=ScrollClick XF86ScrollDown=ScrollDown
XF86ScrollUp=ScrollUp XF86Search=Search XF86Send=Send XF86Shop=Shop XF86Sleep=Sleep XF86Spell=Spell
XF86SplitScreen=SplitScreen XF86Standby=Standby XF86Start=Start XF86Stop=Stop XF86Support=Support
XF86Suspend=Suspend XF86TaskPane=TaskPane XF86Terminal=Terminal XF86ToDoList=ToDoList XF86Tools=Tools
XF86TouchpadOff=TouchpadOff XF86TouchpadOn=TouchpadOn XF86TouchpadToggle=TouchpadToggle XF86Travel=Travel
XF86UWB=UWB XF86User1KB=User1KB XF86User2KB=User2KB XF86UserPB=UserPB XF86VendorHome=VendorHome XF86Video=Video
XF86WLAN=WLAN XF86WWW=WWW XF86WakeUp=WakeUp XF86WebCam=WebCam XF86Word=Word XF86Xfer=Xfer XF86ZoomIn=ZoomIn
XF86ZoomOut=ZoomOut XF86iTouch=iTouch approxeq=U+2248 babovedot=U+1E03 because=U+2235 dabovedot=U+1E0B
dead_dasia=dead_abovereversedcomma dead_psili=dead_abovecomma dead_tilde=dead_perispomeni eightsuperior=U+2078
elementof=U+2208 emptyset=U+2205 ezh=U+0292 fabovedot=U+1E1F fivesuperior=U+2075 foursuperior=U+2074
gcaron=U+01E7 hebrew_qoph=hebrew_kuf hebrew_taw=hebrew_taf ibreve=U+012D kana_middledot=kana_conjunctive
kra=kappa mabovedot=U+1E41 ninesuperior=U+2079 notelementof=U+2209 ohorn=U+01A1 onesubscript=U+2081
oslash=ooblique pabovedot=U+1E57 partdifferential=U+2202 sabovedot=U+1E61 schwa=U+0259 sevensuperior=U+2077
sixsuperior=U+2076 squareroot=U+221A tabovedot=U+1E6B threesubscript=U+2083 twosubscript=U+2082 uhorn=U+01B0
wacute=U+1E83 zerosubscript=U+2080 zerosuperior=U+2070
""".split())


def validate_binding(binding, *, action=None):
    """Return an independent JSON binding, or ``None`` for an explicit disable.

    Key names come from GDK's capture adapter, but this model imports no GTK.
    Unknown modifier flags and malformed key names never become active.
    """
    if action is not None and (not isinstance(action, str) or action not in _ACTIONS):
        raise BindingError("invalid")
    if binding is None:
        return None
    if not isinstance(binding, dict) or set(binding) != {"key", "modifiers"}:
        raise BindingError("invalid")
    key, modifiers = binding["key"], binding["modifiers"]
    if not isinstance(key, str) or not _KEY_NAME.fullmatch(key):
        raise BindingError("invalid")
    if not isinstance(modifiers, (list, tuple, set, frozenset)) or len(modifiers) > 3:
        raise BindingError("invalid")
    if any(not isinstance(modifier, str) for modifier in modifiers):
        raise BindingError("invalid")
    if any(modifier not in _MODIFIERS for modifier in modifiers):
        raise BindingError("modifiers")
    if len(set(modifiers)) != len(modifiers):
        raise BindingError("invalid")
    key = _NATIVE_ALIASES.get(key, key)
    key = _CANONICAL.get(key.casefold(), key.lower() if len(key) == 1 else key)
    if key not in _KNOWN_KEYS:
        raise BindingError("invalid")
    if key in _RESERVED_KEYS or key.startswith("dead_"):
        raise BindingError("reserved")
    flags = frozenset(modifiers)
    if ("alt" in flags and key == "F4") or ({"control", "alt"} <= flags and (
            key in {"Delete", "BackSpace"} or key in {"F" + str(number) for number in range(1, 13)})):
        raise BindingError("reserved")
    if flags == {"control"} and key in {"a", "c", "v", "x", "z", "y"}:
        raise BindingError("reserved")
    if flags == {"control", "shift"} and key == "z":
        raise BindingError("reserved")
    if not flags or flags == {"shift"}:
        if key == "space" and not flags:
            if action not in {None, "speech"}:
                raise BindingError("space")
        elif not _FUNCTION_KEY.fullmatch(key):
            raise BindingError("typing")
    return {"key": key, "modifiers": [modifier for modifier in _MODIFIERS if modifier in flags]}


def _combinations(binding):
    if binding is None:
        return ()
    key = binding["key"]
    return tuple((name, frozenset(binding["modifiers"])) for name in _ALIASES.get(key, (key,)))


def _accelerator(binding):
    if binding is None:
        return ""
    return "".join("<" + _GTK_MODIFIERS[modifier] + ">" for modifier in binding["modifiers"]) + binding["key"]


def default_binding(action):
    """Return the primary default as JSON data; default dispatch keeps all aliases."""
    shortcut = _ACTIONS.get(action) if isinstance(action, str) else None
    if shortcut is None:
        raise BindingError("invalid")
    modifiers, key = shortcut.accelerator.rsplit(">", 1) if ">" in shortcut.accelerator else ("", shortcut.accelerator)
    flags = {name.lower() for name in re.findall(r"<([A-Za-z]+)", modifiers)}
    return {"key": key, "modifiers": [modifier for modifier in _MODIFIERS if modifier in flags]}


def _valid_overrides(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for shortcut in SHORTCUTS:
        if shortcut.action not in value:
            continue
        try:
            result[shortcut.action] = validate_binding(value[shortcut.action], action=shortcut.action)
        except (BindingError, TypeError, ValueError):
            continue
    return result


def normalize_custom_shortcuts(value):
    """Discard invalid/conflicting overrides deterministically, retaining valid swaps.

    Inherited defaults win over overrides. Between two overrides registry order
    wins; restoring a discarded action's default may invalidate another
    override, so the bounded action list is checked until stable.
    """
    overrides = _valid_overrides(value)
    while True:
        owners = {}
        rejected = set()
        for shortcut in SHORTCUTS:
            if shortcut.action not in overrides:
                for combination in shortcut.combinations:
                    owners[combination] = shortcut.action
        for shortcut in SHORTCUTS:
            if shortcut.action not in overrides:
                continue
            combinations = _combinations(overrides[shortcut.action])
            if any(combination in owners for combination in combinations):
                rejected.add(shortcut.action)
            else:
                for combination in combinations:
                    owners[combination] = shortcut.action
        if not rejected:
            return overrides
        for action in rejected:
            del overrides[action]


def effective_bindings(settings=None):
    """Return metadata and actual aliases/accelerators for the selected profile."""
    if not isinstance(settings, dict) or settings.get("shortcut_mode") != "custom":
        return SHORTCUTS
    overrides = normalize_custom_shortcuts(settings.get("custom_shortcuts"))
    return tuple(Shortcut(shortcut.action, _accelerator(overrides[shortcut.action]), shortcut.title,
                          shortcut.group, _combinations(overrides[shortcut.action]), shortcut.reader_only)
                 if shortcut.action in overrides else shortcut for shortcut in SHORTCUTS)


def effective_binding(action, settings=None):
    """Return the selected primary binding, or ``None`` when explicitly disabled."""
    if not isinstance(action, str) or action not in _ACTIONS:
        raise BindingError("invalid")
    if isinstance(settings, dict) and settings.get("shortcut_mode") == "custom":
        overrides = normalize_custom_shortcuts(settings.get("custom_shortcuts"))
        if action in overrides:
            return overrides[action]
    return default_binding(action)


def find_conflict(action, binding, settings=None):
    """Return another action owning any alias, including inherited defaults.

    The candidate may already be present in settings. Do not repair profile
    conflicts here: that could silently remove the very owner the editor must
    report. The editor only commits after this check succeeds.
    """
    if not isinstance(action, str) or action not in _ACTIONS:
        raise BindingError("invalid")
    candidate = _combinations(validate_binding(binding, action=action))
    if not candidate:
        return None
    overrides = _valid_overrides(settings.get("custom_shortcuts")) if isinstance(settings, dict) and settings.get("shortcut_mode") == "custom" else {}
    for shortcut in SHORTCUTS:
        if shortcut.action == action:
            continue
        combinations = _combinations(overrides[shortcut.action]) if shortcut.action in overrides else shortcut.combinations
        if any(combination in combinations for combination in candidate):
            return shortcut.action
    return None


def shortcut_for(key_name, modifiers, *, reading=False, has_book=False, reading_focus=False, settings=None):
    """Resolve exact meaningful modifiers; locks are removed by the GTK adapter.

    Space is deliberately scoped to the reading surface so it cannot consume
    text input, activate a toolbar button, or start narration from a menu.
    """
    combination = (key_name, frozenset(modifiers))
    for shortcut in effective_bindings(settings):
        if combination not in shortcut.combinations:
            continue
        if shortcut.reader_only and (not reading or not has_book):
            return None
        if shortcut.action == "speech" and not reading_focus:
            return None
        return shortcut.action
    return None
