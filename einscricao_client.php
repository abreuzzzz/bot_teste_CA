<?php

declare(strict_types=1);

const EINSCRICAO_BASE_URL = 'https://www.e-inscricao.com';
const EINSCRICAO_LOGIN_PATH = '/users/sign_in';
const EINSCRICAO_CACHE_TTL_SECONDS = 300;
const EINSCRICAO_BROWSER_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36';

class EinscricaoAuthException extends RuntimeException
{
}

function einscricao_json_response(int $status, array $payload): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: GET, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');

    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}

function einscricao_compact_text(string $text): string
{
    return trim(preg_replace('/\s+/', ' ', $text) ?? '');
}

function einscricao_contains(string $haystack, string $needle): bool
{
    if ($needle === '') {
        return true;
    }

    return strpos($haystack, $needle) !== false;
}

function einscricao_lower(string $text): string
{
    if (function_exists('mb_strtolower')) {
        return mb_strtolower($text, 'UTF-8');
    }

    return strtolower($text);
}

function einscricao_substr(string $text, int $start, int $length): string
{
    if (function_exists('mb_substr')) {
        return (string) mb_substr($text, $start, $length, 'UTF-8');
    }

    return (string) substr($text, $start, $length);
}

function einscricao_cache_dir(): string
{
    $dir = __DIR__ . '/cache';
    if (!is_dir($dir)) {
        @mkdir($dir, 0775, true);
    }
    return $dir;
}

function einscricao_cache_key(string $prefix, array $parts): string
{
    return $prefix . '|' . implode('|', $parts);
}

function einscricao_read_cache(string $cacheKey): ?array
{
    $path = einscricao_cache_dir() . '/' . sha1($cacheKey) . '.json';
    if (!is_file($path)) {
        return null;
    }

    $raw = @file_get_contents($path);
    if ($raw === false || $raw === '') {
        return null;
    }

    $decoded = json_decode($raw, true);
    if (!is_array($decoded) || !isset($decoded['savedAt'], $decoded['payload'])) {
        return null;
    }

    $savedAt = (int) $decoded['savedAt'];
    if (time() - $savedAt > EINSCRICAO_CACHE_TTL_SECONDS) {
        return null;
    }

    return is_array($decoded['payload']) ? $decoded['payload'] : null;
}

function einscricao_write_cache(string $cacheKey, array $payload): void
{
    $path = einscricao_cache_dir() . '/' . sha1($cacheKey) . '.json';
    $wrapper = [
        'savedAt' => time(),
        'payload' => $payload,
    ];

    @file_put_contents($path, json_encode($wrapper, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), LOCK_EX);
}

function einscricao_extract_csrf_token(string $html): string
{
    if (preg_match('/<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']\s*\/?\s*>/i', $html, $matches)) {
        return html_entity_decode($matches[1], ENT_QUOTES | ENT_HTML5, 'UTF-8');
    }

    throw new RuntimeException('Nao foi possivel encontrar csrf-token na pagina de login.');
}

function einscricao_format_date_br(DateTimeInterface $date): string
{
    return $date->format('d/m/Y');
}

function einscricao_default_date_range(): array
{
    $today = new DateTimeImmutable('now');
    $firstDay = $today->setDate((int) $today->format('Y'), (int) $today->format('m'), 1)->setTime(0, 0, 0);

    return [
        'startDate' => einscricao_format_date_br($firstDay),
        'endDate' => einscricao_format_date_br($today),
    ];
}

function einscricao_parse_account_ids_from_value(string $value): array
{
    $parts = array_map('trim', explode(',', $value));
    $ids = [];
    foreach ($parts as $part) {
        if (preg_match('/^\d+$/', $part) === 1) {
            $ids[$part] = true;
        }
    }

    $result = array_keys($ids);
    usort($result, static function (string $a, string $b): int {
        return (int) $a <=> (int) $b;
    });
    return $result;
}

function einscricao_to_number_or_null($value): ?float
{
    if (is_int($value) || is_float($value)) {
        return is_finite((float) $value) ? (float) $value : null;
    }

    if (is_string($value)) {
        $normalized = str_replace('.', '', $value);
        $normalized = str_replace(',', '.', $normalized);
        $normalized = preg_replace('/[^\d.-]/', '', $normalized) ?? '';
        if ($normalized === '') {
            return null;
        }
        return is_numeric($normalized) ? (float) $normalized : null;
    }

    return null;
}

function einscricao_collect_numeric_candidates($raw, string $path = '', array &$output = []): array
{
    if ($raw === null) {
        return $output;
    }

    if (is_array($raw)) {
        foreach ($raw as $key => $value) {
            $nextPath = $path === '' ? (string) $key : $path . '.' . (string) $key;
            einscricao_collect_numeric_candidates($value, $nextPath, $output);
        }
        return $output;
    }

    $numeric = einscricao_to_number_or_null($raw);
    if ($numeric !== null) {
        $output[] = ['path' => $path, 'value' => $numeric];
    }

    return $output;
}

function einscricao_pick_by_keywords(array $candidates, array $keywords): ?float
{
    $keywords = array_map(static function (string $k): string {
        return einscricao_lower($k);
    }, $keywords);
    foreach ($candidates as $entry) {
        $path = einscricao_lower((string) ($entry['path'] ?? ''));
        $ok = true;
        foreach ($keywords as $kw) {
            if (!einscricao_contains($path, $kw)) {
                $ok = false;
                break;
            }
        }
        if ($ok) {
            return (float) $entry['value'];
        }
    }

    return null;
}

function einscricao_derive_balances(array $rawPayload): array
{
    $candidates = einscricao_collect_numeric_candidates($rawPayload);

    $saldoAtual =
        einscricao_pick_by_keywords($candidates, ['saldo', 'dispon']) ??
        einscricao_pick_by_keywords($candidates, ['balance', 'available']) ??
        einscricao_pick_by_keywords($candidates, ['saldo', 'resgate']) ??
        0.0;

    $saldoAReceber =
        einscricao_pick_by_keywords($candidates, ['saldo', 'liberar']) ??
        einscricao_pick_by_keywords($candidates, ['saldo', 'futuro']) ??
        einscricao_pick_by_keywords($candidates, ['balance', 'future']) ??
        einscricao_pick_by_keywords($candidates, ['receber']) ??
        0.0;

    return [
        'saldoAtual' => $saldoAtual,
        'saldoAReceber' => $saldoAReceber,
    ];
}

function einscricao_collect_ids_from_text(string $text, array &$collector): void
{
    if (preg_match_all('/\/financial_accounts\/(\d+)(?:\.json)?/i', $text, $matches) === 1 || !empty($matches[1])) {
        foreach ($matches[1] as $id) {
            $collector[(string) $id] = true;
        }
    }

    if (preg_match_all('/(?:financial_account_id|data-account-id)\D+(\d{2,})/i', $text, $matches2) === 1 || !empty($matches2[1])) {
        foreach ($matches2[1] as $id) {
            $collector[(string) $id] = true;
        }
    }
}

function einscricao_collect_ids_from_json($raw, array &$collector, string $path = ''): void
{
    if (!is_array($raw)) {
        return;
    }

    foreach ($raw as $key => $value) {
        $keyStr = (string) $key;
        $nextPath = $path === '' ? $keyStr : $path . '.' . $keyStr;

        if (($keyStr === 'financial_account_id' || $keyStr === 'account_id') && preg_match('/^\d+$/', (string) $value) === 1) {
            $collector[(string) $value] = true;
        }

        if ($keyStr === 'id' && preg_match('/financial_accounts?/i', $path) === 1 && preg_match('/^\d+$/', (string) $value) === 1) {
            $collector[(string) $value] = true;
        }

        if (is_string($value)) {
            einscricao_collect_ids_from_text($value, $collector);
        }

        if (is_array($value)) {
            einscricao_collect_ids_from_json($value, $collector, $nextPath);
        }
    }
}

final class EinscricaoClient
{
    private $cookies = [];
    private $email;
    private $password;

    public function __construct(string $email, string $password)
    {
        $this->email = $email;
        $this->password = $password;
    }

    public function login(): void
    {
        $warmup = $this->request('GET', EINSCRICAO_BASE_URL . '/', [
            'headers' => $this->buildHeaders([
                'referer' => EINSCRICAO_BASE_URL . '/',
            ]),
        ]);

        if ($warmup['status'] === 403) {
            $this->throwHttpStepError('Bloqueio no warm-up da sessao', $warmup);
        }

        $loginPage = $this->request('GET', EINSCRICAO_BASE_URL . EINSCRICAO_LOGIN_PATH, [
            'headers' => $this->buildHeaders([
                'referer' => EINSCRICAO_BASE_URL . '/',
            ]),
        ]);

        if ($loginPage['status'] < 200 || $loginPage['status'] >= 300) {
            $this->throwHttpStepError('Falha ao abrir login do e-inscricao', $loginPage);
        }

        $csrf = einscricao_extract_csrf_token($loginPage['body']);

        $formBody = http_build_query([
            'utf8' => '✓',
            'authenticity_token' => $csrf,
            'user[email]' => $this->email,
            'user[password]' => $this->password,
            'commit' => 'Entrar',
        ]);

        $loginResponse = $this->request('POST', EINSCRICAO_BASE_URL . EINSCRICAO_LOGIN_PATH, [
            'headers' => $this->buildHeaders([
                'referer' => EINSCRICAO_BASE_URL . EINSCRICAO_LOGIN_PATH,
                'contentType' => 'application/x-www-form-urlencoded',
                'extra' => [
                    'Origin' => EINSCRICAO_BASE_URL,
                ],
            ]),
            'body' => $formBody,
        ]);

        if ($loginResponse['status'] === 403) {
            $this->throwHttpStepError('Login bloqueado no e-inscricao', $loginResponse);
        }

        if ($loginResponse['status'] < 300 || $loginResponse['status'] >= 400) {
            throw new EinscricaoAuthException('Login sem redirect esperado. HTTP ' . $loginResponse['status'] . '.');
        }

        if ($this->cookieHeader() === '') {
            throw new EinscricaoAuthException('Login sem cookie de sessao.');
        }
    }

    public function discoverAccountIds(): array
    {
        $sources = ['/financial_accounts', '/financial_accounts.json'];
        $collector = [];

        foreach ($sources as $source) {
            $response = $this->request('GET', EINSCRICAO_BASE_URL . $source, [
                'headers' => $this->buildHeaders([
                    'referer' => EINSCRICAO_BASE_URL . '/financial_accounts',
                    'accept' => 'application/json, text/html, */*',
                ]),
            ]);

            if (in_array($response['status'], [401, 403], true)) {
                throw new EinscricaoAuthException('Sessao expirada ao descobrir contas financeiras.');
            }

            if ($response['status'] >= 300 && $response['status'] < 400 && einscricao_contains((string) ($response['headers']['location'] ?? ''), '/users/sign_in')) {
                throw new EinscricaoAuthException('Descoberta de contas redirecionou para login.');
            }

            if ($response['status'] < 200 || $response['status'] >= 300) {
                continue;
            }

            $body = $response['body'];
            einscricao_collect_ids_from_text($body, $collector);

            $parsed = json_decode($body, true);
            if (is_array($parsed)) {
                einscricao_collect_ids_from_json($parsed, $collector);
            }
        }

        $ids = array_keys($collector);
        usort($ids, static function (string $a, string $b): int {
            return (int) $a <=> (int) $b;
        });
        return $ids;
    }

    public function getFinancialSummary(string $accountId, string $startDate, string $endDate, string $filter = 'limit_date_filter', string $eventId = '0'): array
    {
        $endpoint = EINSCRICAO_BASE_URL . '/financial_accounts/' . rawurlencode($accountId) . '.json';
        $query = http_build_query([
            'financial_accounts_form[event_id]' => $eventId,
            'financial_accounts_form[filter]' => $filter,
            'financial_accounts_form[start_date]' => $startDate,
            'financial_accounts_form[end_date]' => $endDate,
        ]);

        $response = $this->request('GET', $endpoint . '?' . $query, [
            'headers' => $this->buildHeaders([
                'referer' => EINSCRICAO_BASE_URL . '/financial_accounts',
                'accept' => 'application/json, text/plain, */*',
            ]),
        ]);

        if (in_array($response['status'], [401, 403], true)) {
            if ($response['status'] === 403) {
                $this->throwHttpStepError('Acesso bloqueado no endpoint financeiro', $response);
            }
            throw new EinscricaoAuthException('Sessao expirada ou sem autorizacao no endpoint financeiro.');
        }

        if ($response['status'] >= 300 && $response['status'] < 400 && einscricao_contains((string) ($response['headers']['location'] ?? ''), '/users/sign_in')) {
            throw new EinscricaoAuthException('Endpoint financeiro redirecionou para login.');
        }

        if ($response['status'] < 200 || $response['status'] >= 300) {
            throw new RuntimeException('Falha no endpoint financeiro. HTTP ' . $response['status'] . '.');
        }

        $raw = json_decode($response['body'], true);
        if (!is_array($raw)) {
            throw new RuntimeException('Resposta JSON invalida no endpoint financeiro.');
        }

        $rawPath = einscricao_cache_dir() . '/raw-financial-account-' . $accountId . '.json';
        if (!is_file($rawPath)) {
            @file_put_contents($rawPath, json_encode($raw, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
        }

        $balances = einscricao_derive_balances($raw);

        return [
            'accountId' => $accountId,
            'saldoAtual' => (float) $balances['saldoAtual'],
            'saldoAReceber' => (float) $balances['saldoAReceber'],
            'raw' => $raw,
        ];
    }

    private function request(string $method, string $url, array $options = []): array
    {
        $ch = curl_init($url);
        if ($ch === false) {
            throw new RuntimeException('Falha ao inicializar cURL.');
        }

        $headersMap = $options['headers'] ?? [];
        $headers = [];
        foreach ($headersMap as $name => $value) {
            $headers[] = $name . ': ' . $value;
        }

        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HEADER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CUSTOMREQUEST => strtoupper($method),
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_ENCODING => '',
            CURLOPT_CONNECTTIMEOUT => 20,
            CURLOPT_TIMEOUT => 45,
        ]);

        if (isset($options['body'])) {
            curl_setopt($ch, CURLOPT_POSTFIELDS, (string) $options['body']);
        }

        $rawResponse = curl_exec($ch);
        if ($rawResponse === false) {
            $error = curl_error($ch);
            curl_close($ch);
            throw new RuntimeException('Erro de rede cURL: ' . $error);
        }

        $headerSize = (int) curl_getinfo($ch, CURLINFO_HEADER_SIZE);
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);

        $headerText = substr($rawResponse, 0, $headerSize);
        $body = (string) substr($rawResponse, $headerSize);

        $parsedHeaders = $this->parseHeaders($headerText);
        $this->updateCookiesFromSetCookie($parsedHeaders['set-cookie'] ?? []);

        return [
            'status' => $status,
            'headers' => $parsedHeaders,
            'body' => $body,
        ];
    }

    private function parseHeaders(string $headerText): array
    {
        $headers = [];
        $setCookies = [];
        $lines = preg_split('/\r\n|\n|\r/', $headerText) ?: [];
        foreach ($lines as $line) {
            if (!einscricao_contains($line, ':')) {
                continue;
            }

            [$name, $value] = array_map('trim', explode(':', $line, 2));
            if ($name === '') {
                continue;
            }

            $nameLower = strtolower($name);
            if ($nameLower === 'set-cookie') {
                $setCookies[] = $value;
                continue;
            }

            $headers[$nameLower] = $value;
        }

        if (!empty($setCookies)) {
            $headers['set-cookie'] = $setCookies;
        }

        return $headers;
    }

    private function updateCookiesFromSetCookie(array $setCookies): void
    {
        foreach ($setCookies as $rawCookie) {
            $firstPart = explode(';', (string) $rawCookie, 2)[0] ?? '';
            $separator = strpos($firstPart, '=');
            if ($separator === false || $separator <= 0) {
                continue;
            }

            $name = trim(substr($firstPart, 0, $separator));
            $value = trim(substr($firstPart, $separator + 1));
            if ($name !== '') {
                $this->cookies[$name] = $value;
            }
        }
    }

    private function cookieHeader(): string
    {
        if (empty($this->cookies)) {
            return '';
        }

        $pairs = [];
        foreach ($this->cookies as $name => $value) {
            $pairs[] = $name . '=' . $value;
        }
        return implode('; ', $pairs);
    }

    private function buildHeaders(array $config = []): array
    {
        $headers = [
            'Accept' => $config['accept'] ?? 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language' => 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cache-Control' => 'no-cache',
            'Pragma' => 'no-cache',
            'User-Agent' => EINSCRICAO_BROWSER_UA,
            'Upgrade-Insecure-Requests' => '1',
        ];

        $cookieHeader = $this->cookieHeader();
        if ($cookieHeader !== '') {
            $headers['Cookie'] = $cookieHeader;
        }

        if (!empty($config['referer'])) {
            $headers['Referer'] = (string) $config['referer'];
        }

        if (!empty($config['contentType'])) {
            $headers['Content-Type'] = (string) $config['contentType'];
        }

        if (!empty($config['extra']) && is_array($config['extra'])) {
            foreach ($config['extra'] as $k => $v) {
                $headers[(string) $k] = (string) $v;
            }
        }

        return $headers;
    }

    private function throwHttpStepError(string $step, array $response): void
    {
        $bodySnippet = einscricao_substr(einscricao_compact_text((string) ($response['body'] ?? '')), 0, 280);
        $headers = $response['headers'] ?? [];
        $cfRay = (string) ($headers['cf-ray'] ?? 'n/a');
        $server = (string) ($headers['server'] ?? 'n/a');
        $status = (int) ($response['status'] ?? 0);

        throw new RuntimeException(
            $step . ' HTTP ' . $status . '. server=' . $server . ' cf-ray=' . $cfRay . ' body=' . ($bodySnippet !== '' ? $bodySnippet : '(vazio)')
        );
    }
}

function einscricao_load_credentials(): array
{
    $email = getenv('EINSCRICAO_EMAIL') ?: '';
    $password = getenv('EINSCRICAO_PASSWORD') ?: '';
    $accountIds = getenv('EINSCRICAO_ACCOUNT_ID') ?: '';

    $localConfigPath = __DIR__ . '/config.local.php';
    if (is_file($localConfigPath)) {
        $config = require $localConfigPath;
        if (is_array($config)) {
            if ($email === '' && !empty($config['EINSCRICAO_EMAIL'])) {
                $email = (string) $config['EINSCRICAO_EMAIL'];
            }
            if ($password === '' && !empty($config['EINSCRICAO_PASSWORD'])) {
                $password = (string) $config['EINSCRICAO_PASSWORD'];
            }
            if ($accountIds === '' && !empty($config['EINSCRICAO_ACCOUNT_ID'])) {
                $accountIds = (string) $config['EINSCRICAO_ACCOUNT_ID'];
            }
        }
    }

    return [
        'email' => $email,
        'password' => $password,
        'accountIdsRaw' => $accountIds,
    ];
}
