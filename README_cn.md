[English](README.md) | [绠€浣撲腑鏂嘳(README_cn.md)

# sustech_survival

<p align="center">
  <img src="src/sustech_survival/resources/logo-full-transparent.svg"
       alt="sustech_survival" width="360">
</p>

`sustech_survival` 鏄竴涓厑璁稿湪 API 灞傞潰璋冪敤鍗楃澶у悇鏈嶅姟绯荤粺鐨?Python 妯″潡銆傚畠婊¤冻 SUSTech 瀛︾敓鍦?BB銆乀IS銆佸浘涔﹂銆丳MS 绛夌郴缁熺殑鏃ュ父闇€姹傘€?
閫氳繃鍦ㄤ唬鐮佸眰闈㈡墦閫氳繖浜涙湇鍔★紝鎴戜滑绠€鍖栦簡鏍″洯绯荤粺鐨勪娇鐢紝鎻愪緵浜嗕竴鏉￠€氬線涓€у寲鏍″洯浣撻獙鐨勬嵎寰勶紝鏇撮噸瑕佺殑鏄?鈥斺€?鎺ュ叆骞舵杩?AI 鍔╂墜杩涘叆浣犵殑鏍″洯鐢熸椿銆?
[![GitHub](https://img.shields.io/badge/github-repo-blue.svg)](https://github.com/dumixthestpd/sustech_survival)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-orange.svg)](./LICENSE)

---

## 鍔熻兘

### 鏍″洯绯荤粺

- **姣曞崥骞冲彴 Blackboard Learn** (`bb`)
- **鏁欏淇℃伅鏈嶅姟 TIS** (`tis`)
- **鍥句功棣?SUSTech Library** (`lib`)
- **缁熶竴韬唤璁よ瘉 SSO** (`sso`) 鈥?鍏变韩璁よ瘉搴曞骇
- **鑱斿垱鎵撳嵃 PMS** (`pms`)
- **澶栦簨 SUSTech Global** (`ws`)
- **缃戜笂鍔炰簨澶у巺 E-Hall** (`booking`)
- **鐗涘搰璇剧▼璇勪环 NCES** (`nces`)

### 鑷缓妯″潡

- **selectcourse** 鈥?TIS 閫夎锛氭祻瑙堣绋嬨€佸姞閫€閫夈€佺鐞嗚喘鐗╄溅銆?- **faculty** 鈥?鏁欏笀淇℃伅鐩綍锛氭寜瀛﹂櫌鍒楄〃銆佸叏鏂囨悳绱€佷釜浜轰富椤垫煡璇€?- **transit** 鈥?鏍″洯宸村＋涓庢琛屽鑸細鏃跺埢琛ㄣ€佸疄鏃?GPS銆佽矾绾胯鍒掋€?- **calendar** 鈥?鍗楃澶ф牎鍘嗕笌鏃ユ湡鏅鸿兘锛氫粠 GitHub 涓婄殑 `sustech-calendar` 浠撳簱鍔犺浇 JSON锛岃В鏋?(鍛ㄦ, 鏄熸湡) 鈫?鏃ユ湡锛屽鐞嗚ˉ璇炬棩璋冩崲銆傚湪绾挎暟鎹负鏉冨▉婧愶紱鏈湴瑕嗙洊鐢ㄤ簬缂栬緫涓殑鏁版嵁銆?- **ical** 鈥?宸查€夎绋嬬殑 `.ics` 瀵煎嚭銆備綅浜?`selectcourse.ical`锛岄€氳繃 webui 鐨?`GET /api/tis/ical` 鎺ュ叆銆?- **webui** 鈥?Flask 鍗曢〉搴旂敤锛屾暣鍚?TIS 閫夎鐣岄潰銆佸叕浜ゅ湴鍥俱€丯CES 鎮诞鍗＄墖銆乮Cal 瀵煎嚭銆傚惎鍔細`python -m sustech_survival.webui serve`銆?- **context** 鈥?涓?AI 鍔╂墜璁捐鐨勬瘡鏃ュ揩鐓э細鏃ユ湡銆佸懆娆°€佹渶杩戜綔涓?鑰冭瘯/涓婅鏃堕棿銆佸ぉ姘斻€丄QI銆?- **papers** 鈥?瀛︽湳璁烘枃鎼滅储涓庝笅杞斤紝瑕嗙洊 CrossRef銆丆NKI銆乄oS銆丷SC銆?
---

## 蹇€熷紑濮?
### 1. 瀹夎

CLI锛坄click`锛夊凡鍖呭惈鍦ㄦ牳蹇冧緷璧栦腑 鈥斺€?`pip install sustech_survival` 鍚屾椂瀹夎 Python API 鍜?`sustech` 鍛戒护銆?
鍙€夋墿灞曟寜闇€瀹夎锛?
- `webui` 鈥?Flask SPA锛歍IS 閫夎鐣岄潰 + 鍏氦鍦板浘 + NCES 鎮诞鍗＄墖
- `nces` 鈥?Anubis PoW 姹傝В鍣紙NCES 鍒楄〃鎶撳彇鐢級
- `papers` 鈥?cloudscraper锛堢粫杩囧嚭鐗堝晢缃戠珯鐨?requests 鎷︽埅锛?- `all` 鈥?浠ヤ笂鍏ㄩ儴

```bash
# 浠婚€夊叾涓€锛?pip install "sustech_survival"               # API + CLI
pip install "sustech_survival[webui]"        # + Web 鐣岄潰
pip install "sustech_survival[all]"          # 鍏ㄩ儴
```

### 2. 韬唤璁よ瘉

缁熶竴 CAS 璁よ瘉搴曞骇浣嶄簬 `sustech_survival/sso/authorizer.py`銆?姣忎釜绯荤粺锛圔B銆乀IS銆佸浘涔﹂銆佸浜嬨€丳MS銆丯CES銆佸満鍦伴绾︾瓑锛夌殑鐧诲綍閮藉彧鏄竴涓?`Authorizer` 瀛愮被 鈥斺€?閫変竴涓苟璋冪敤 `ensure()`锛?
```python
from sustech_survival.sso import TISAuth

auth = TISAuth()                       # 姣忕被鍗曚緥
ok, reason = auth.ensure()             # 妫€鏌ヤ細璇濓紝杩囨湡鍒欒嚜鍔ㄥ埛鏂?auth.session.get("/xszykb/querydangqianxnxq")   # 浣跨敤宸茶璇佺殑浼氳瘽

# 鎴栦娇鐢ㄨ楗板櫒锛?from sustech_survival.sso import require_auth

@require_auth(TISAuth)
def my_function(auth=None):
    r = auth.session.get(...)
```

鍑嵁鏂囦欢鏌ユ壘椤哄簭锛堝厛鎵惧埌鐨勪紭鍏堬級锛?
1. `SUSTECH_CREDENTIALS` 鐜鍙橀噺 鈥斺€?鍑嵁鏂囦欢鐨勫畬鏁磋矾寰?2. `~/.config/sustech_survival/credentials.txt` 鈥斺€?XDG 椋庢牸鐨勭敤鎴烽厤缃?3. `./credentials.txt` 鈥斺€?褰撳墠宸ヤ綔鐩綍
4. 浠庡寘婧愮爜鍚戜笂鎼滅储 鈥斺€?寮€鍙?鍙紪杈戝畨瑁?
鏍煎紡锛歚瀛﹀彿:瀵嗙爜`銆備細璇濅粎淇濆瓨鍦?*鍐呭瓨涓?* 鈥斺€?涓嶅啓 `session.json` 鍒扮鐩樸€?
鍚勬ā鍧楃殑 CLI 鎻愪緵 `session login | check | refresh`锛?
```bash
sustech bb session login
sustech tis session refresh
python -m sustech_survival.lib.login   # 鍥句功棣?Primo
```

### 3. 绀轰緥鐢ㄦ硶

璁剧疆瀹屾垚鍚庣殑涓や釜甯哥敤宸ヤ綔娴侊細

**姣忔棩蹇収锛堜负 AI 鍔╂墜璁捐锛夛細**

```python
from sustech_survival.context import Context

ctx = Context(level="normal")   # terse / normal / verbose
print(ctx.to_str())
# 鈫?Today is [2026-07-04], [Saturday]
# 鈫?Next BB deadline: [Experiment 5] 鈥?Due in 3 days
# 鈫?Next TIS exam: [...final...]
```

**Web 鐣岄潰锛堟渶甯哥敤锛夛細**

```bash
python -m sustech_survival.webui
```

娴忚鍣ㄦ墦寮€ `http://localhost:61019` 鈥斺€?TIS 閫夎鐣岄潰锛堝惈鍐茬獊姹傝В锛夈€?鏍″洯宸村＋鍦板浘锛堝疄鏃?GPS锛夈€佹瘡涓绋嬬殑 NCES 鎮诞鍗＄墖銆?
---

## 鐩稿叧椤圭洰

- **[sustech-calendar](https://github.com/dumixthestpd/sustech-calendar)** 鈥?鍗楃澶ф牎鍘嗭紙瀛︽湡銆佸伐浣滄棩銆佽妭鍋囨棩锛夈€俙calendar` 妯″潡鍦ㄨ繍琛屾椂鍔犺浇鍏?JSON锛涘湪绾挎暟鎹负鏉冨▉婧愩€?
---

## 鏋舵瀯

```
sustech_survival/
鈹溾攢鈹€ bb/                鈫?Blackboard Learn / 姣曞崥
鈹溾攢鈹€ tis/               鈫?TIS / 鏁欏淇℃伅鏈嶅姟
鈹?  鈹斺攢鈹€ classroom/     鈫?TIS 鏁欏鏌ヨ + 鍦哄湴鍊熺敤 (cdjy)
鈹溾攢鈹€ lib/               鈫?鍥句功棣?(Primo)
鈹?  鈹斺攢鈹€ booking/       鈫?IC 鍥句功棣嗛绾?鈹溾攢鈹€ sso/               鈫?鍏变韩璁よ瘉搴曞骇锛圕AS + Shibboleth锛?鈹溾攢鈹€ pms/               鈫?鑱斿垱鎵撳嵃
鈹溾攢鈹€ transit/           鈫?鏍″洯宸村＋鍦板浘锛堣嚜寤猴級
鈹溾攢鈹€ faculty/           鈫?鏁欏笀鐩綍锛堣嚜寤猴級
鈹溾攢鈹€ selectcourse/      鈫?TIS 閫夎杈呭姪锛堣嚜寤猴級
鈹?  鈹斺攢鈹€ ical.py        鈫?.ics 瀵煎嚭锛堣嚜寤猴級
鈹溾攢鈹€ booking/           鈫?E-Hall / 缃戜笂鍔炰簨澶у巺
鈹溾攢鈹€ ws/                鈫?SUSTech Global / 澶栦簨
鈹溾攢鈹€ context/           鈫?姣忔棩蹇収锛堣嚜寤猴級
鈹溾攢鈹€ nces/              鈫?鐗涘搰璇剧▼璇勪环
鈹溾攢鈹€ papers/            鈫?CrossRef / CNKI / WoS / RSC锛堣嚜寤猴級
鈹溾攢鈹€ calendar.py        鈫?鏍″巻涓庢棩鏈熸櫤鑳斤紙鑷缓锛?鈹溾攢鈹€ exceptions.py
鈹斺攢鈹€ webui/             鈫?Flask 鍗曢〉搴旂敤锛堣嚜寤猴級锛歍IS + transit + NCES + iCal
```

---

## 璋冭瘯

鏈€蹇殑杩唬鏂瑰紡鏄紑鍙戞ā寮忓畨瑁呭埌宸ヤ綔鐩綍锛岀劧鍚庤窇 pytest锛堥渶瑕佺湡瀹炲嚟鎹級銆?
```bash
git clone https://github.com/dumixthestpd/sustech_survival
cd sustech_survival
pip install -e ".[all]"

# 鍗曞厓娴嬭瘯锛坢ocked锛屽揩閫燂級
python -m pytest src/test/ -v

# 鐜板満娴嬭瘯锛堥渶瑕佺湡瀹炵殑 BB/TIS 鍑嵁锛岃瑙?tests/锛?python -m pytest src/test/ -v --live
```

---

## 寰呭姙

- [x] 缁熶竴鐨?`sustech.sso.Authorizer().ensure()` 鈥斺€?鎶婂悇绯荤粺鐨勮璇佸悎骞朵负涓€娆?CAS 璋冪敤銆傗渽 宸插畬鎴?- [ ] 鏇村ソ鐨勬湰鍦板寲锛堟竻鏅板尯鍒嗕腑鑻辨枃锛?- [ ] 鏍″洯椋熷爞姣忔棩鑿滃崟閫氱煡
- [ ] NCES 璇勮鎽樿锛堥厤缃?API key 鏃跺彲鐢紱涔熷彲閫氳繃 skill 鏂囨。瀹炵幇锛?
---

## 鍏充簬寮€鍙戣€?
鏈ā鍧楃敱 **dumixthestpd**锛堝崡绉戝ぇ闈炶绠楁満涓撲笟鏈鐢燂級寮€鍙戯紝浠栦粎璐熻矗瀹忚璁捐銆傛湰妯″潡 99% 鐨勪唬鐮佺敱 AI 鍔╂墜缂栧啓锛屾垜浠竻妤氬湴鎰忚瘑鍒扮敱姝ゅ甫鏉ョ殑浠ｇ爜璐ㄩ噺闂銆傛垜浠杩庢洿澶氬悓瀛﹀姞鍏ュ紑鍙?鈥斺€?鍦?GitHub Issues 鍙戣捣璁ㄨ鍗冲彲銆備篃娆㈣繋鐩存帴鎻?PR銆?
---

## 鑷磋阿

绔欏湪宸ㄤ汉鐨勮偐鑶€涓婏細

- **[xCipHanD/SUSTech_AutoScheduler](https://github.com/xCipHanD/SUSTech_AutoScheduler)** 鈥?TIS 璇剧▼鏁版嵁妯″瀷涓庢椂闂寸紪鐮佽В鏋愮殑涓昏鍙傝€冿紱浠栦滑鐨?bug 鍒楄〃甯姪鎴戜滑鍦ㄨ嚜宸辩殑閫夎鍣ㄤ腑瑙勯伩闂銆?- **[lethal233/sustech-tis-converter](https://github.com/lethal233/sustech-tis-converter)** 鈥?TIS REST 鎺ュ彛鐨勬棭鏈熸帰绱€?- **[Fros1er/SUSTechTISHelper](https://github.com/Fros1er/SUSTechTISHelper)** 鈥?TIS 杈呭姪宸ュ叿銆?- **[SUSTech-CRA/awesome-sustech-service-tools](https://github.com/SUSTech-CRA/awesome-sustech-service-tools)** 鈥?鍗楃澶ф湇鍔″伐鍏蜂笌 API 鍙傝€冪殑绮鹃€夊垪琛ㄣ€?
瀹屾暣鍒楄〃涓庡凡鐭?bug 瑙?[CREDITS.md](./CREDITS.md)銆?
---

## 璁稿彲璇?
[PolyForm Noncommercial License 1.0.0](./LICENSE) 鈥?浠呴檺闈炲晢涓氫娇鐢紝鐩稿悓鏂瑰紡鍏变韩锛屼繚鐣欑讲鍚嶃€