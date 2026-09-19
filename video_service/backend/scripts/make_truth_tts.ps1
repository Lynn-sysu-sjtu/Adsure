# 合成基准广告的口播。每句单独出一个 wav，之后由 make_truth_ad.py 按已知偏移放进时间轴。
# 需要 Windows 自带的中文 TTS 语音（Microsoft Huihui / Yaoyao / Kangkang）。
param([Parameter(Mandatory = $true)][string]$OutDir)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Add-Type -AssemblyName System.Speech

$lines = @(
  @{ f = "vo1.wav"; t = "本品采用国家级配方" },          # 埋点：国家级（应命中 L1）
  @{ f = "vo2.wav"; t = "每天两粒轻松改善睡眠" },        # 对照：改善（法定保健功能，不应命中）
  @{ f = "vo3.wav"; t = "上市以来销量第一值得信赖" }     # 埋点：销量第一（应命中 L1）
)

foreach ($l in $lines) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $voice = $s.GetInstalledVoices() |
    Where-Object { $_.VoiceInfo.Culture.Name -eq "zh-CN" } |
    Select-Object -First 1
  if (-not $voice) {
    Write-Error "没有找到 zh-CN 语音，无法合成口播。"
    exit 1
  }
  $s.SelectVoice($voice.VoiceInfo.Name)
  $s.Rate = -1
  $p = Join-Path $OutDir $l.f
  $s.SetOutputToWaveFile($p)
  $s.Speak($l.t)
  $s.Dispose()
  "{0}  「{1}」" -f $l.f, $l.t
}
