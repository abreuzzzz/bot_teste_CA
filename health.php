<?php

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    echo json_encode([]);
    exit;
}

$cacheDir = __DIR__ . '/cache';
$cacheExists = is_dir($cacheDir);
$cacheWritable = $cacheExists ? is_writable($cacheDir) : @mkdir($cacheDir, 0775, true);

$payload = [
    'ok' => true,
    'phpVersion' => PHP_VERSION,
    'sapi' => PHP_SAPI,
    'curlLoaded' => extension_loaded('curl'),
    'jsonLoaded' => extension_loaded('json'),
    'mbstringLoaded' => extension_loaded('mbstring'),
    'opensslLoaded' => extension_loaded('openssl'),
    'allowUrlFopen' => (bool) ini_get('allow_url_fopen'),
    'cacheDir' => $cacheDir,
    'cacheDirExists' => $cacheExists,
    'cacheDirWritable' => (bool) $cacheWritable,
    'time' => gmdate('c'),
];

echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
