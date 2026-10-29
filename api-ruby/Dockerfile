FROM ruby:3.3-slim-bookworm@sha256:245eafdd393b298a1bcc6948504b59a117539d46a7fd12ebb8bd2c103f814566
ENV LANG=C.UTF-8 BUNDLE_WITHOUT=development:test
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libssl-dev && rm -rf /var/lib/apt/lists/*
COPY Gemfile Gemfile.lock* ./
RUN bundle install && bundle clean --force
COPY app.rb config.ru puma.rb ./
USER 10001:10001
CMD ["bundle", "exec", "puma", "-C", "puma.rb"]
