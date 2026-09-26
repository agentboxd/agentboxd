/**
 * Where `agentboxd login` keeps the API key: one JSON file in the OS config directory, readable by the
 * current user only (directory 0700, file 0600 on macOS/Linux; on Windows the file sits in the user's
 * own %APPDATA%, which other users can't read).
 *
 *   AGENTBOXD_CONFIG_DIR   overrides the directory (tests, several profiles)
 *   Windows                %APPDATA%\agentboxd\config.json
 *   macOS / Linux          $XDG_CONFIG_HOME/agentboxd/config.json, default ~/.config/agentboxd/config.json
 */
import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';

export interface StoredConfig {
  api_key?: string;
  base_url?: string;
}

export function configDir(env: Record<string, string | undefined>, platform: string = process.platform): string {
  if (env.AGENTBOXD_CONFIG_DIR) return env.AGENTBOXD_CONFIG_DIR;
  if (platform === 'win32') return path.join(env.APPDATA || path.join(homedir(), 'AppData', 'Roaming'), 'agentboxd');
  return path.join(env.XDG_CONFIG_HOME || path.join(homedir(), '.config'), 'agentboxd');
}

export const configFile = (dir: string) => path.join(dir, 'config.json');

export function readConfig(dir: string): StoredConfig {
  const file = configFile(dir);
  if (!existsSync(file)) return {};
  try {
    const parsed = JSON.parse(readFileSync(file, 'utf8')) as unknown;
    return parsed && typeof parsed === 'object' ? (parsed as StoredConfig) : {};
  } catch {
    throw new Error(`${file} is not valid JSON: fix it or delete it and run \`agentboxd login\` again.`);
  }
}

export function writeConfig(dir: string, config: StoredConfig): string {
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  const file = configFile(dir);
  writeFileSync(file, JSON.stringify(config, null, 2) + '\n', { mode: 0o600 });
  // `mode` only applies when the file is created: tighten an existing file too (a no-op on Windows).
  chmodSync(file, 0o600);
  return file;
}

export function deleteConfig(dir: string): boolean {
  const file = configFile(dir);
  if (!existsSync(file)) return false;
  rmSync(file);
  return true;
}
