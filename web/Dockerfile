FROM node:22-alpine AS build

WORKDIR /opt/enterprise-ai-platform/web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN npm run build

FROM node:22-alpine
WORKDIR /opt/enterprise-ai-platform/web
ENV NODE_ENV=production
COPY --from=build /opt/enterprise-ai-platform/web ./
EXPOSE 3000
CMD ["npm", "run", "start"]
