#!/usr/bin/env node
import { launch } from '../lib/launcher.mjs';

try {
  process.exitCode = await launch(process.argv.slice(2));
} catch (error) {
  console.error(`DocSync: ${error.message}`);
  process.exitCode = 1;
}
