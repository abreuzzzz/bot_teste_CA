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

$defaults = einscricao_default_date_range();
$startDate = isset($_GET['startDate']) && is_string($_GET['startDate']) && $_GET['startDate'] !== ''
    ? $_GET['startDate']
    : $defaults['startDate'];
$endDate = isset($_GET['endDate']) && is_string($_GET['endDate']) && $_GET['endDate'] !== ''
    ? $_GET['endDate']
    : $defaults['endDate'];
$filter = isset($_GET['filter']) && is_string($_GET['filter']) && $_GET['filter'] !== ''
    ? $_GET['filter']
    : 'limit_date_filter';
$eventId = isset($_GET['eventId']) && is_string($_GET['eventId']) && $_GET['eventId'] !== ''
    ? $_GET['eventId']
    : '0';

$queryAccountIds = isset($_GET['accountId']) && is_string($_GET['accountId']) ? $_GET['accountId'] : '';
$wantsDiscovery = strtolower($queryAccountIds) === 'all' || (isset($_GET['discover']) && $_GET['discover'] === '1');
$includeRaw = isset($_GET['debugRaw']) && $_GET['debugRaw'] === '1';

$parsedFromQuery = strtolower($queryAccountIds) === 'all' ? [] : einscricao_parse_account_ids_from_value($queryAccountIds);
$parsedFromEnv = einscricao_parse_account_ids_from_value((string) $credentials['accountIdsRaw']);
$accountIds = !empty($parsedFromQuery) ? $parsedFromQuery : $parsedFromEnv;

$initialKeyIds = !empty($accountIds) ? implode(',', $accountIds) : 'auto';
$initialCacheKey = einscricao_cache_key('resumo', [$initialKeyIds, $startDate, $endDate, $filter, $eventId]);

if (!$includeRaw && !$wantsDiscovery && !empty($accountIds)) {
    $cached = einscricao_read_cache($initialCacheKey);
    if ($cached !== null) {
        einscricao_json_response(200, $cached);
        exit;
    }
}

try {
    $client = new EinscricaoClient($email, $password);
    $client->login();

    if ($wantsDiscovery || empty($accountIds)) {
        $discovered = $client->discoverAccountIds();
        if (!empty($discovered)) {
            $accountIds = $discovered;
        }
    }

    $accountIds = array_values(array_unique($accountIds));
    usort($accountIds, static fn(string $a, string $b): int => (int) $a <=> (int) $b);

    if (empty($accountIds)) {
        einscricao_json_response(404, [
            'message' => 'Nenhum accountId disponivel para consulta.',
            'hint' => 'Use ?accountId=123,456 ou ?accountId=all para descoberta automatica.',
        ]);
        exit;
    }

    $finalCacheKey = einscricao_cache_key('resumo', [implode(',', $accountIds), $startDate, $endDate, $filter, $eventId]);
    if (!$includeRaw) {
        $cachedFinal = einscricao_read_cache($finalCacheKey);
        if ($cachedFinal !== null) {
            einscricao_json_response(200, $cachedFinal);
            exit;
        }
    }

    $contas = [];
    $accountErrors = [];
    $rawByAccount = [];

    foreach ($accountIds as $accountId) {
        try {
            $summary = $client->getFinancialSummary($accountId, $startDate, $endDate, $filter, $eventId);
            $contas[] = [
                'accountId' => $accountId,
                'saldoAtual' => (float) $summary['saldoAtual'],
                'saldoAReceber' => (float) $summary['saldoAReceber'],
            ];

            if ($includeRaw) {
                $rawByAccount[$accountId] = $summary['raw'];
            }
        } catch (Throwable $errorByAccount) {
            $accountErrors[] = [
                'accountId' => $accountId,
                'message' => $errorByAccount->getMessage(),
            ];
        }
    }

    if (empty($contas)) {
        $firstError = $accountErrors[0]['message'] ?? 'Nao foi possivel consultar nenhuma conta.';
        throw new RuntimeException($firstError);
    }

    $payload = [
        'saldoAtual' => array_reduce($contas, static fn(float $sum, array $row): float => $sum + (float) ($row['saldoAtual'] ?? 0), 0.0),
        'saldoAReceber' => array_reduce($contas, static fn(float $sum, array $row): float => $sum + (float) ($row['saldoAReceber'] ?? 0), 0.0),
        'atualizadoEm' => gmdate('c'),
        'accountIds' => $accountIds,
        'contas' => $contas,
        'accountErrors' => $accountErrors,
    ];

    if ($includeRaw) {
        $payload['rawByAccount'] = $rawByAccount;
    } else {
        einscricao_write_cache($finalCacheKey, $payload);
        if ($finalCacheKey !== $initialCacheKey) {
            einscricao_write_cache($initialCacheKey, $payload);
        }
    }

    einscricao_json_response(200, $payload);
} catch (EinscricaoAuthException $authError) {
    einscricao_json_response(401, [
        'message' => 'Falha de autenticacao no e-inscricao.',
        'details' => $authError->getMessage(),
    ]);
} catch (Throwable $error) {
    $message = $error->getMessage();

    if (str_contains($message, 'HTTP 403')) {
        einscricao_json_response(502, [
            'message' => 'Acesso ao e-inscricao bloqueado (HTTP 403).',
            'details' => $message,
            'hint' => 'O upstream pode estar bloqueando trafego automatizado deste host. Solicite whitelist ao e-inscricao.',
        ]);
        exit;
    }

    einscricao_json_response(500, [
        'message' => 'Erro ao consultar resumo financeiro.',
        'details' => $message !== '' ? $message : 'Erro desconhecido',
    ]);
}
