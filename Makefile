
example-bing-driving-distance:
	python3 solve.py \
		--site-data=example_sites.csv \
		--days=3 \
		--max-stops-per-day=2 \
		--annealing-param-decay=0.994 \
		--bing-maps-api-key=${BING_MAPS_API_KEY} \
		--bing-travel-mode=driving \
		--bing-cost=distance

example-bing-driving-time:
	python3 solve.py \
		--site-data=example_sites.csv \
		--days=3 \
		--max-stops-per-day=2 \
		--annealing-param-decay=0.994 \
		--bing-maps-api-key=${BING_MAPS_API_KEY} \
		--bing-travel-mode=driving \
		--cost-property=time

example-rymans-data:
	python3 solve.py \
		--site-data=sites.csv \
		--days=7 \
		--max-stops-per-day=3 \
		--annealing-param-decay=0.991 \
		--bing-maps-api-key=${BING_MAPS_API_KEY} \
		--bing-travel-mode=driving \
		--cost-property=time

format:
	black .