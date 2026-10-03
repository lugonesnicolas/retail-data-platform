{% test not_in_future(model, column_name, tolerance_hours=var('future_tolerance_hours', 1)) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} > now() + interval '{{ tolerance_hours }} hours'
{% endtest %}
