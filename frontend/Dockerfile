# Stage 1: Install dependencies and build the Next.js application
FROM node:20-slim AS builder

# Set working directory
WORKDIR /app

# Copy package.json and lock file, then install dependencies
COPY package.json package-lock.json* yarn.lock* pnpm-lock.yaml* ./
RUN if [ -f yarn.lock ]; then yarn install --frozen-lockfile; elif [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; else npm ci; fi

# Copy the rest of the application code
COPY . .

# Build the Next.js application
# This creates the production build in the .next directory
RUN npm run build

# Stage 2: Run the production Next.js application
FROM node:20-slim AS runner

# Set environment variables for production
ENV NODE_ENV production

# Set working directory
WORKDIR /app

# Copy necessary files from the builder stage
# Copy the production build output (.next directory)
COPY --from=builder /app/.next ./.next
# Copy the public directory (static assets)
COPY --from=builder /app/public ./public
# Copy package.json and node_modules required for production runtime
# Note: Only production dependencies are needed here. npm ci in builder handles dev deps separation.
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules

# Expose the port Next.js runs on (default is 3000)
EXPOSE 3000

# Command to run the production Next.js server
CMD ["npm", "start"]

