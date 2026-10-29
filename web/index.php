<?php
// PHP demonstration of the original flow: form -> API -> link summary.
function esc($value) { return htmlspecialchars((string)$value, ENT_QUOTES, 'UTF-8'); }
$api = ($_GET['api'] ?? 'python') === 'ruby' ? 'ruby' : 'python';
$url = $_GET['url'] ?? 'http://paginas/pagina01.html';
$links = null; $err = null;
if (isset($_GET['extract'])) {
    $context = stream_context_create(['http'=>['timeout'=>12, 'ignore_errors'=>true]]);
    $body = @file_get_contents('http://api-'.$api.':8080/api/extract?url='.rawurlencode($url), false, $context);
    $links = $body !== false ? json_decode($body, true) : null;
    if (!is_array($links) || isset($links['error'])) { $err = $links['error'] ?? 'API indisponível. Inicie a API selecionada.'; $links = null; }
}
?>
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Trabalho 4 | Link Extractor</title>
<style>body{font:17px system-ui;background:#101728;color:#edf4ff;max-width:960px;margin:50px auto;padding:20px}h1{color:#55d9ff}form{display:grid;gap:12px}input,select,button{font:inherit;padding:12px;border-radius:8px}button{background:#4064ff;color:white;border:0}a{color:#55d9ff}li{margin:8px 0}.error{color:#ff8eac}</style></head><body>
<p>COMPUTAÇÃO DISTRIBUÍDA / TRABALHO 4</p><h1>Link Extractor</h1>
<p>Interface PHP de demonstração. Escolha uma das dez páginas controladas.</p>
<form><select name="api"><option value="python" <?= $api==='python'?'selected':'' ?>>Python</option><option value="ruby" <?= $api==='ruby'?'selected':'' ?>>Ruby</option></select>
<select name="url"><?php for($i=1;$i<=10;$i++): $option=sprintf('http://paginas/pagina%02d.html',$i); ?><option <?= $url===$option?'selected':'' ?>><?=esc($option)?></option><?php endfor ?></select>
<button name="extract" value="1">Extrair links</button></form>
<?php if($err): ?><p class="error"><?=esc($err)?></p><?php endif ?>
<?php if($links!==null): ?><h2><?=count($links)?> links extraídos / <?=esc($api)?></h2><p><?=esc($url)?></p><ul><?php foreach($links as $link): ?><li><?=esc($link['text'])?> → <?=esc($link['href'])?></li><?php endforeach ?></ul><?php endif ?>
<footer><p>Adaptado de <a href="https://github.com/ibnesayeed/linkextractor">ibnesayeed/linkextractor</a> (MIT).</p></footer></body></html>
