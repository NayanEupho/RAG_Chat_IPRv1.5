# Use the official Bun image
FROM oven/bun:1 AS base

WORKDIR /app

# Copy dependency files
COPY package.json bun.lock ./

# Install dependencies
RUN bun install --frozen-lockfile

# Copy the frontend source code
COPY . .

# Build the Next.js application
RUN bun run build

# Expose the frontend port
EXPOSE 3000

# Start the Next.js server
CMD ["bun", "start"]
