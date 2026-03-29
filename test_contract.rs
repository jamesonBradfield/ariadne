#[test]
fn test_new_entity() {
    let entity = Entity::new();
    assert_eq!(entity.health, 100.0);
    assert_eq!(entity.armor, 50.0);
    assert!(!entity.is_dead);
}

#[test]
fn test_take_damage() {
    let mut entity = Entity::new();
    entity.take_damage(50.0);
    assert_eq!(entity.health, 50.0);
}

#[test]
fn test_heal() {
    let mut entity = Entity::new();
    entity.take_damage(60.0);
    entity.heal(20.0);
    assert_eq!(entity.health, 60.0);
}