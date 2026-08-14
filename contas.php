<?php

declare(strict_types=1);

require __DIR__ . '/einscricao_client.php';

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    einscricao_json_response(204, []);
    exit;
}

$credentials = einscricao_load_credentials();
$email = $credentials['email'];
$password = $credentials['password'];

if ($email === '' || $password === '') {
    einscricao_json_response(500, [
        'message' => 'Credenciais do e-inscricao ausentes.',
        'details' => 'Defina EINSCRICAO_EMAIL e EINSCRICAO_PASSWORD (env ou config.local.php).',
    ]);
    exit;
}

$cacheKey = einscricao_cache_key('contas', ['discover']);
$cached = einscricao_read_cache($cacheKey);
if ($cached !== null) {
    einscricao_json_response(200, $cached);
    exit;
}

try {
    $client = new EinscricaoClient($email, $password);
    $client->login();
    $accountIds = $client->discoverAccountIds();

    if (empty($accountIds)) {
        einscricao_json_response(404, [
            'message' => 'Nenhuma conta financeira encontrada automaticamente.',
            'hint' => 'Abra o modulo financeiro no e-inscricao e confirme que sua conta possui extratos acessiveis.',
        ]);
        exit;
    }

    $payload = [
        'accountIds' => $accountIds,
        'total' => count($accountIds),
        'atualizadoEm' => gmdate('c'),
    ];

    einscricao_write_cache($cacheKey, $payload);
    einscricao_json_response(200, $payload);
} catch (EinscricaoAuthException $authError) {
    einscricao_json_response(401, [
        'message' => 'Falha de autenticacao no e-inscricao.',
        'details' => $authError->getMessage(),
    ]);
} catch (Throwable $error) {
    $message = $error->getMessage();

    if (einscricao_contains($message, 'HTTP 403')) {
        einscricao_json_response(502, [
            'message' => 'Acesso ao e-inscricao bloqueado (HTTP 403).',
            'details' => $message,
            'hint' => 'O upstream pode estar bloqueando trafego automatizado deste host. Solicite whitelist ao e-inscricao.',
        ]);
        exit;
    }

    einscricao_json_response(500, [
        'message' => 'Erro ao descobrir contas financeiras.',
        'details' => $message !== '' ? $message : 'Erro desconhecido',
    ]);
}
