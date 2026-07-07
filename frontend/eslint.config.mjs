import js from "@eslint/js";
import nextPlugin from "@next/eslint-plugin-next";
import tsPlugin from "@typescript-eslint/eslint-plugin";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import globals from "globals";

const tsRecommended = tsPlugin.configs["flat/recommended"];
const reactSettings = {
  react: {
    version: "detect",
  },
};

export default [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "next-env.d.ts",
      "tsconfig.tsbuildinfo",
    ],
  },
  {
    files: ["**/*.{js,jsx,ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
  },
  js.configs.recommended,
  ...tsRecommended,
  {
    ...reactPlugin.configs.flat.recommended,
    settings: reactSettings,
  },
  {
    ...reactPlugin.configs.flat["jsx-runtime"],
    settings: reactSettings,
  },
  reactHooksPlugin.configs.flat.recommended,
  nextPlugin.configs["core-web-vitals"],
  {
    files: ["**/*.{js,jsx,ts,tsx}"],
    settings: {
      next: {
        rootDir: ["./"],
      },
      ...reactSettings,
    },
    rules: {
      "@next/next/no-html-link-for-pages": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
];
