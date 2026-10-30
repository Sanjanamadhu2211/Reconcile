import js from "@eslint/js";
import tseslint from "@typescript-eslint/parser";
import globals from "globals";

export default [
  {
    files: ["src/**/*.ts", "src/**/*.tsx", "**/*.ts", "**/*.tsx"],
    languageOptions: {
      globals: globals.browser,
      parser: tseslint,
    },
    ignores: [
      ".next/**",
      "node_modules/**",
      "public/**",
      ".next/types/**",
      ".next/static/**",
      "**/*.js",
      "**/*.mjs",
      "**/*.cjs",
    ],
    ...js.configs.recommended,
    rules: {
      // Basic rules
      "prefer-const": "error",
      "no-var": "error",
      "no-unused-vars": "error",
    },
  },
];
