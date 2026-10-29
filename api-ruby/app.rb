# Experimental adaptation of step6; no file logging in the request path.
require 'sinatra/base'
require 'nokogiri'
require 'net/http'
require 'uri'
require 'json'
require 'redis'

class Extractor < Sinatra::Base
  CACHE = ENV.fetch('CACHE_ENABLED', 'false').downcase == 'true'
  TIMEOUT = ENV.fetch('UPSTREAM_TIMEOUT', '5').to_f
  set :environment, :production
  set :logging, false
  set :show_exceptions, false
  set :host_authorization, permitted_hosts: ['api-ruby', 'localhost', '127.0.0.1']

  helpers do
    def output(payload, code = 200, cache = nil)
      status code
      content_type 'application/json', charset: 'utf-8'
      headers 'X-Implementation' => 'ruby'
      headers 'X-Cache' => cache if cache
      payload.is_a?(String) ? payload : JSON.generate(payload)
    end

    def store
      # Per-thread connection avoids serializing all Puma threads on one socket.
      # In OFF mode this method is never invoked; no Redis object is constructed.
      Thread.current[:t4_redis] ||= Redis.new(url: ENV.fetch('REDIS_URL'), timeout: 2)
    end

    def extract_url(url)
      return output({error: 'URL outside controlled corpus'}, 400) unless
        url.match?(%r{\Ahttp://paginas/pagina(?:0[1-9]|10)\.html\z})
      key = 't4:ruby:' + url
      if CACHE
        cached = store.get(key)
        return output(cached, 200, 'HIT') unless cached.nil?
      end
      uri = URI(url)
      http = Net::HTTP.new(uri.host, uri.port, nil)
      http.open_timeout = TIMEOUT
      http.read_timeout = TIMEOUT
      response = http.get(uri.request_uri)
      return output({error: 'Upstream unavailable'}, 502) unless response.code == '200'
      doc = Nokogiri::HTML(response.body.force_encoding('UTF-8'))
      links = doc.css('a[href]').map do |a|
        text = a.text.gsub(/[[:space:]]+/, ' ').strip
        {text: text.empty? ? '[IMG]' : text, href: URI.join(url, a['href']).to_s}
      end
      body = JSON.generate(links)
      store.set(key, body) if CACHE
      output(body, 200, CACHE ? 'MISS' : 'OFF')
    rescue Redis::BaseError
      output({error: 'Redis unavailable'}, 503)
    rescue Timeout::Error, SocketError, SystemCallError, EOFError, Net::HTTPBadResponse
      output({error: 'Upstream unavailable'}, 502)
    end
  end

  get('/health') do
    output({status: 'ok', implementation: 'ruby', cache_enabled: CACHE,
            workers: 2, threads_per_worker: 4})
  end
  get('/api/extract') { extract_url(params.fetch('url', '')) }
  get('/api/*') do
    # Sinatra normalizes repeated slashes in splat; preserve the original URI.
    raw = request.env['REQUEST_URI'] || request.path_info
    url = raw.split('?', 2).first.delete_prefix('/api/')
    url += '?' + request.query_string unless request.query_string.empty?
    extract_url(url)
  end
end
