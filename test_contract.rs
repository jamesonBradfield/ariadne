#[test]
fn test_take_damage_with_armor_mitigation() {
    let mut entity = Entity::new();
    let initial_health = entity.health;
    let damage = 100.0;
    let armor = entity.armor;
    let mitigation = damage * (armor / (armor + 100.0));
    let expected_health = initial_health - (damage - mitigation);
    entity.take_damage(damage);
    assert!((entity.health - expected_health).abs() < 0.01);
}

#[test]
fn test_take_damage_transitions_to_death() {
    let mut entity = Entity::new();
    entity.health = 10.0;
    entity.take_damage(100.0);
    assert!(entity.is_dead);
}

#[test]
fn test_take_damage_no_death_when_health_positive() {
    let mut entity = Entity::new();
    entity.health = 100.0;
    entity.take_damage(50.0);
    assert!(!entity.is_dead);
}